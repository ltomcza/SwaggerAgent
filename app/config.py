from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_HOST: str = "localhost"
    DB_PORT: int = 1433
    DB_NAME: str = "swagger_agent"
    DB_USER: str = "sa"
    DB_PASSWORD: str = "YourStrong!Passw0rd"
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-5-mini"
    LLM_TEMPERATURE: float = 0.0
    LLM_ANALYSIS_MODEL: str = "gpt-5-mini"
    LLM_ANALYSIS_TEMPERATURE: float = 0.2
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"mssql+pyodbc://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
            f"?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
        )


settings = Settings()
