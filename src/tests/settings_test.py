import pytest

from settings import load_settings


@pytest.fixture(autouse=True)
def limpar_env(monkeypatch):
    """Garante que cada teste começa sem nenhuma env var do pipeline setada,
    e também impede que o load_dotenv() leia o arquivo .env real do disco."""
    # Remove todas as variáveis de ambiente que o pipeline usa
    for var in [
        "API_URL",
        "TIMEOUT_SEC",
        "SALDO_LIMITE_BAIXO",
        "SALDO_LIMITE_ALTO",
        "OPT_OUT_PATH",
        "AUDIT_LOG_PATH",
        "REPORT_PATH",
        "PAGE_SIZE",
        "GEMINI_API_KEY",
        "GEMINI_MODEL",
        "ICON_URL",
        "WRAP_NEWS_WIDTH",
        "API_USERNAME",
        "API_PASSWORD",
    ]:
        monkeypatch.delenv(var, raising=False)

    # Impede que a função load_dotenv() (importada dentro de settings.py) leia o .env
    # Isso faz com que apenas as variáveis setadas via monkeypatch.setenv nos testes sejam consideradas.
    import settings as settings_module
    monkeypatch.setattr(settings_module, "load_dotenv", lambda: None)

    # Muda o diretório de trabalho para um temporário, garantindo que nenhum .env seja encontrado
    monkeypatch.chdir(pytest.importorskip("tempfile").mkdtemp())


class TestApiUrlObrigatoria:
    def test_sem_api_url_levanta_erro_claro_em_vez_de_usar_default_morto(self):
        with pytest.raises(ValueError, match="API_URL"):
            load_settings()

    def test_api_url_valida_mas_sem_credenciais_levanta_erro(self, monkeypatch):
        monkeypatch.setenv("API_URL", "https://exemplo.com")

        with pytest.raises(ValueError, match="API_USERNAME"):
            load_settings()

    def test_api_url_com_barra_no_final_e_normalizada(self, monkeypatch):
        monkeypatch.setenv("API_URL", "https://users-api-python.onrender.com/")
        monkeypatch.setenv("API_USERNAME", "admin")
        monkeypatch.setenv("API_PASSWORD", "senha-fake")

        settings = load_settings()

        assert settings.api_url == "https://users-api-python.onrender.com"


class TestValidacaoDeLimitesDeSaldo:
    def test_limites_default_sao_validos(self, monkeypatch):
        monkeypatch.setenv("API_URL", "https://exemplo.com")
        monkeypatch.setenv("API_USERNAME", "admin")
        monkeypatch.setenv("API_PASSWORD", "senha-fake")

        settings = load_settings()

        assert settings.saldo_limite_baixo < settings.saldo_limite_alto

    def test_limite_baixo_maior_que_alto_levanta_erro(self, monkeypatch):
        monkeypatch.setenv("API_URL", "https://exemplo.com")
        monkeypatch.setenv("API_USERNAME", "admin")
        monkeypatch.setenv("API_PASSWORD", "senha-fake")
        monkeypatch.setenv("SALDO_LIMITE_BAIXO", "50000")
        monkeypatch.setenv("SALDO_LIMITE_ALTO", "1000")

        with pytest.raises(ValueError, match="SALDO_LIMITE_BAIXO"):
            load_settings()


class TestDefaults:
    def test_valores_default_sao_aplicados_quando_env_nao_definida(self, monkeypatch):
        monkeypatch.setenv("API_URL", "https://exemplo.com")
        monkeypatch.setenv("API_USERNAME", "admin")
        monkeypatch.setenv("API_PASSWORD", "senha-fake")

        settings = load_settings()

        assert settings.opt_out_path == "data/opt_out.csv"
        assert settings.audit_log_path == "logs/audit_log.jsonl"
        assert settings.gemini_model == "gemini-2.5-flash"
        assert settings.page_size == 50

    def test_env_var_sobrescreve_default(self, monkeypatch):
        monkeypatch.setenv("API_URL", "https://exemplo.com")
        monkeypatch.setenv("API_USERNAME", "admin")
        monkeypatch.setenv("API_PASSWORD", "senha-fake")
        monkeypatch.setenv("PAGE_SIZE", "10")

        settings = load_settings()

        assert settings.page_size == 10