from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = "US Census Data Assistant"
    use_llm: bool = os.getenv("USE_LLM", "false").lower() == "true"
    llm_base_url: str = os.getenv("LLM_BASE_URL", "").rstrip("/")
    llm_api_key: str | None = os.getenv("LLM_API_KEY")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    snowflake_account: str | None = os.getenv("SNOWFLAKE_ACCOUNT")
    snowflake_user: str | None = os.getenv("SNOWFLAKE_USER")
    snowflake_password: str | None = os.getenv("SNOWFLAKE_PASSWORD")
    snowflake_role: str | None = os.getenv("SNOWFLAKE_ROLE")
    snowflake_warehouse: str | None = os.getenv("SNOWFLAKE_WAREHOUSE")
    snowflake_database: str = os.getenv(
        "SNOWFLAKE_DATABASE",
        "US_OPEN_CENSUS_DATA__NEIGHBORHOOD_INSIGHTS__FREE_DATASET",
    )
    snowflake_schema: str = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    query_timeout_seconds: int = int(os.getenv("QUERY_TIMEOUT_SECONDS", "30"))

    @property
    def has_hosted_llm_config(self) -> bool:
        return self.use_llm and bool(self.llm_base_url and self.llm_model and self.llm_api_key)

    @property
    def has_snowflake_credentials(self) -> bool:
        return all(
            [
                self.snowflake_account,
                self.snowflake_user,
                self.snowflake_password,
                self.snowflake_warehouse,
            ]
        )


settings = Settings()
