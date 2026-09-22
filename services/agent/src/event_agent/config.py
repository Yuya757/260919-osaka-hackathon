from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gcp_project_id: str | None = None
    gcp_region: str = "asia-northeast1"
    gemini_model: str = "gemini-3.8-flash"
    # Gemini の呼び出し先。Cloud Run のリージョン（gcp_region）とは別で、
    # 最新モデルは global エンドポイントにしか無い
    gemini_location: str = "global"
    agent_demo_mode: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "https://osaka-hackathon-260919.web.app"
    )
    port: int = 8080
    # Firestore永続化（§7）。既定はOFFで、デモと評価はインメモリのまま動く。
    # Emulatorに繋ぐときは FIRESTORE_EMULATOR_HOST をクライアント側が読む。
    firestore_enabled: bool = False
    firestore_database: str = "(default)"
    max_search_queries: int = 8
    max_candidates: int = 30
    max_model_calls: int = 15
    # 検索の期間指定（この日数より新しいページ）と、ページ取得の同時数
    search_recency_days: int = 180
    fetch_concurrency: int = 6
    model_call_timeout_seconds: float = 60.0
    locate_concurrency: int = 4
    # ADR-008: ユーザー起点の Grounding 探索を受け付けるか。既定は費用の安全側
    manual_runs_enabled: bool = False
    # 一覧に出す共有プールの範囲（lastSeenAt がこの日数以内）
    pool_window_days: int = 30
    # 既知ページを再抽出するまでの日数
    known_url_refresh_days: int = 7
    # 1 日あたりの Grounding 検索の上限（全 Run 合計）
    daily_grounding_cap: int = 40
    verified_confidence_threshold: float = 0.8
    # 公式・主催者の根拠が無く集約サイトだけを出典とするイベントを表示する下限
    # （画面設計書§8-2）。compute_confidence の重み上、集約サイト単独ホストの
    # 理論最大は 0.65 なので、0.60 は「title と dates.eventStart の両方に根拠が
    # あり、矛盾も無い」場合しか通さない。S-01 のデュアル日付表示が成立する
    # 最小条件と一致する。
    aggregator_only_min_confidence: float = 0.60
    # §6.7 優先度4のタイトル類似度。0.80 は実測で決めた値で、
    # 「大阪データ活用カンファレンス」と同名+接尾辞の併合が 0.800 のため。
    # 高スコアの別イベント（2026 vs 2027 = 0.952、Kansai vs Kanto = 0.878）は
    # 開催開始日と地域の AND 条件で弾くので、この閾値でも誤併合しない。
    title_similarity_threshold: float = 0.80
    # 1.1.0: チャットのシステム命令にサンドイッチ防御とカナリアを追加（§10.1）
    prompt_version: str = "chat-1.1.0"
    extraction_schema_version: str = "extract-1.0.0"
    validation_rule_version: str = "1.1.0"
    # 抽出が0件のときデモカタログで補う。実運用とデモの両立用。評価では False。
    demo_catalog_fallback: bool = True
    # 進捗バナーを見せるためだけの待ち時間。評価では 0 にする。
    step_delay_seconds: float = 0.1
    eval_repeat_count: int = 3
    # 定期Runの冪等キーに混ぜる版番号（§9.3）。収集条件を変えて同じ日にもう一度
    # 走らせたいときに上げる。
    run_schedule_version: str = "daily-1"
    ekispert_api_key: str | None = None

    @property
    def use_vertex(self) -> bool:
        if self.agent_demo_mode:
            return False
        return bool(self.gcp_project_id and self.gcp_project_id.strip())

    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
