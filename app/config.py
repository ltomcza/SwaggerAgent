from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_TYPE: str = "postgres"  # "postgres" or "sqlserver"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "swagger_agent"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
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
        if self.DB_TYPE == "sqlserver":
            return (
                f"mssql+pyodbc://{self.DB_USER}:{self.DB_PASSWORD}"
                f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
                f"?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
            )
        # Default: postgres
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


settings = Settings()
