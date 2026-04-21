import importlib


def test_embedding_config_multilingual_env_sets_model(monkeypatch):
    monkeypatch.setenv("RAG_EMBED_MULTILINGUAL", "1")
    monkeypatch.delenv("RAG_EMBED_ST_MODEL", raising=False)

    mod = importlib.import_module("src.rag.embeddings")
    cfg = mod.EmbeddingConfig()

    assert cfg.multilingual_preferred is True
    assert cfg.st_model_name == "intfloat/multilingual-e5-base"


def test_embedding_config_explicit_model_overrides_default(monkeypatch):
    monkeypatch.setenv("RAG_EMBED_MULTILINGUAL", "1")
    monkeypatch.setenv("RAG_EMBED_ST_MODEL", "sentence-transformers/paraphrase-multilingual-mpnet-base-v2")

    mod = importlib.import_module("src.rag.embeddings")
    cfg = mod.EmbeddingConfig()

    assert cfg.multilingual_preferred is True
    assert cfg.st_model_name == "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"


def test_auto_mode_prefers_st_in_multilingual_mode(monkeypatch):
    mod = importlib.import_module("src.rag.embeddings")

    calls = []

    def fake_init_st(self):
        calls.append("st")
        self._backend = object()
        self._backend_name = "st/fake"
        self.dimension = 384

    def fake_init_ollama(self):
        calls.append("ollama")
        self._backend = object()
        self._backend_name = "ollama/fake"
        self.dimension = 384

    monkeypatch.setattr(mod.EmbeddingModel, "_init_st", fake_init_st)
    monkeypatch.setattr(mod.EmbeddingModel, "_init_ollama", fake_init_ollama)

    cfg = mod.EmbeddingConfig(backend="auto", multilingual_preferred=True)
    model = mod.EmbeddingModel(cfg)

    assert model.backend_name == "st/fake"
    assert calls == ["st"]
