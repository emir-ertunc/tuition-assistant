from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # values are read from environment variables or the .env file
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/tuition_db"

    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_issuer: str = "tuition-api"
    jwt_audience: str = "tuition-clients"

    # on azure the gateway adds this value as the X-Gateway-Key header. when it is set, /api
    # requests without it are rejected, so nobody can skip the gateway. empty = check is off
    gateway_key: str = ""
    # public address of the api (the gateway), swagger "try it out" sends requests there
    public_base_url: str = ""


settings = Settings()
