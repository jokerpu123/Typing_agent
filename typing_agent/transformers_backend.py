"""Slow correctness baseline: raw Base-model continuation, no chat template."""
from functools import lru_cache


def make_constraint():
    from pypinyin import Style, pinyin
    from .decoding import PinyinConstraint

    @lru_cache(maxsize=32768)
    def readings(char):
        if not ('\u3400' <= char <= '\u9fff'):
            return ()
        result = pinyin(char, style=Style.NORMAL, heteronym=True, errors=lambda _: [])
        return tuple(sorted(set(result[0]))) if result else ()

    return PinyinConstraint(readings)


class TransformersBackend:
    def __init__(self, model_path, context, device="cuda", context_tokens=512):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.device = device
        if context_tokens < 1:
            raise ValueError("context_tokens must be positive")
        self.context_tokens = context_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path, local_files_only=True, trust_remote_code=False,
            dtype=torch.float16 if device == "cuda" else torch.float32,
            attn_implementation="eager",
        ).to(device).eval()
        self.set_context(context)
        special = set(self.tokenizer.all_special_ids)
        self.token_text = {}
        for token_id in range(len(self.tokenizer)):
            if token_id in special:
                continue
            text = self.tokenizer.decode([token_id], clean_up_tokenization_spaces=False)
            # Partial UTF-8 tokens are deliberately excluded in this first version.
            if text and all('\u3400' <= char <= '\u9fff' for char in text):
                self.token_text[token_id] = text

    def set_context(self, context):
        """Reuse loaded weights across requests. Caller must serialize requests."""
        self.context = self.tokenizer.encode(context, add_special_tokens=False)[-self.context_tokens:]
        if not self.context:
            fallback = self.tokenizer.bos_token_id
            if fallback is None:
                fallback = self.tokenizer.eos_token_id
            if fallback is None:
                raise ValueError("Supply nonempty context for this tokenizer")
            self.context = [fallback]

    def log_probs(self, prefix):
        torch = self.torch
        inputs = torch.tensor([self.context + list(prefix)], device=self.device)
        with torch.inference_mode():
            logits = self.model(input_ids=inputs, use_cache=False).logits[0, -1].float()
            scores = torch.log_softmax(logits, dim=-1).cpu().tolist()
        return {token_id: scores[token_id] for token_id in self.token_text}

    def predict_next_words(self, limit=5):
        """One forward pass: rank short Han tokens as continuation suggestions.

        Tokens are not linguistic words; this prototype returns 2–6 character
        words/phrases represented by a single complete token, not whole sentences.
        """
        scores = self.log_probs(())
        eligible = (token for token, text in self.token_text.items() if 2 <= len(text) <= 6)
        ranked = sorted(eligible, key=lambda token: scores[token], reverse=True)
        return list(dict.fromkeys(self.token_text[token] for token in ranked))[:limit]
