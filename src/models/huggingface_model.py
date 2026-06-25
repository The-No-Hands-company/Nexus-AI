from __future__ import annotations

import gc
import threading
from typing import AsyncIterator

from .model_base import GenerateOptions, GenerateResult, ModelBase


class HuggingFaceModel(ModelBase):

    def __init__(
        self,
        model_id: str,
        device: str = "auto",
        load_in_4bit: bool = False,
        load_in_8bit: bool = False,
        trust_remote_code: bool = False,
    ) -> None:
        self.model_id = model_id
        self.model_path = model_id
        self.device = device
        self.load_in_4bit = load_in_4bit
        self.load_in_8bit = load_in_8bit
        self.trust_remote_code = trust_remote_code
        self._model = None
        self._tokenizer = None
        self.loaded = False

    def load(self) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            raise ImportError(
                "transformers and torch are required for HuggingFace models. "
                "Install with: pip install transformers torch"
            )

        quantization_config = None
        if self.load_in_4bit or self.load_in_8bit:
            try:
                from transformers import BitsAndBytesConfig
                if self.load_in_4bit:
                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_quant_type="nf4",
                        bnb_4bit_compute_dtype=torch.bfloat16,
                    )
                else:
                    quantization_config = BitsAndBytesConfig(load_in_8bit=True)
            except ImportError:
                pass

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id,
            trust_remote_code=self.trust_remote_code,
        )
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            device_map=self.device,
            torch_dtype="auto" if not (self.load_in_4bit or self.load_in_8bit) else None,
            quantization_config=quantization_config,
            trust_remote_code=self.trust_remote_code,
        )
        self._model.eval()
        self.loaded = True

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        self.loaded = False
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def generate(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> GenerateResult:
        if not self._model or not self._tokenizer or not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")
        opts = options or GenerateOptions()
        import torch

        inputs = self._tokenizer(prompt, return_tensors="pt")
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        stop_tokens = []
        if opts.stop:
            stop_tokens = [
                tid for s in opts.stop
                for tid in self._tokenizer.encode(s, add_special_tokens=False)
            ]

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=opts.max_tokens,
                temperature=opts.temperature if opts.temperature > 0 else None,
                top_p=opts.top_p,
                top_k=opts.top_k if opts.top_k > 0 else None,
                repetition_penalty=opts.repeat_penalty,
                do_sample=opts.temperature > 0,
                seed=opts.seed,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
                suppress_tokens=stop_tokens or None,
            )

        prompt_len = inputs["input_ids"].shape[1]
        generated = outputs[0][prompt_len:]
        text = self._tokenizer.decode(generated, skip_special_tokens=True).strip()

        stop_reason = "stop"
        if len(generated) >= opts.max_tokens:
            stop_reason = "max_tokens"

        return GenerateResult(
            text=text,
            tokens_prompt=prompt_len,
            tokens_generated=len(generated),
            stop_reason=stop_reason,
            model_path=self.model_id,
        )

    async def stream(
        self,
        prompt: str,
        options: GenerateOptions | None = None,
    ) -> AsyncIterator[str]:
        if not self._model or not self._tokenizer or not self.loaded:
            raise RuntimeError("Model not loaded. Call load() first.")
        opts = options or GenerateOptions()
        from transformers import TextIteratorStreamer

        inputs = self._tokenizer(prompt, return_tensors="pt")
        device = next(self._model.parameters()).device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        streamer = TextIteratorStreamer(
            self._tokenizer,
            skip_prompt=True,
            skip_special_tokens=True,
        )

        gen_kwargs = dict(
            **inputs,
            max_new_tokens=opts.max_tokens,
            temperature=opts.temperature if opts.temperature > 0 else None,
            top_p=opts.top_p,
            top_k=opts.top_k if opts.top_k > 0 else None,
            repetition_penalty=opts.repeat_penalty,
            do_sample=opts.temperature > 0,
            seed=opts.seed,
            pad_token_id=self._tokenizer.pad_token_id,
            eos_token_id=self._tokenizer.eos_token_id,
            streamer=streamer,
        )

        thread = threading.Thread(
            target=self._model.generate,
            kwargs=gen_kwargs,
            daemon=True,
        )
        thread.start()

        for token in streamer:
            if token:
                yield token
