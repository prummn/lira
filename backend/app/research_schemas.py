from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal


class ResearchSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    profile_id: str | None = Field(default=None, max_length=100)
    idle_seconds: int = Field(default=180, ge=0, le=3600)
    start_remaining: int = Field(default=50, ge=10, le=95)
    stop_remaining: int = Field(default=35, ge=5, le=90)
    long_reserve: int = Field(default=30, ge=10, le=90)
    calls_per_hour: int = Field(default=6, ge=1, le=18)
    maintenance_enabled: bool = False
    maintenance_interval_minutes: int = Field(default=720, ge=30, le=10080)
    maintenance_calls_per_run: int = Field(default=3, ge=1, le=12)
    maintenance_scope: Literal['library', 'enabled_collections'] = 'library'

    @model_validator(mode='after')
    def thresholds(self):
        if self.start_remaining <= self.stop_remaining:
            raise ValueError('启动阈值必须高于停止阈值')
        return self


class ScopeUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    focus: str = Field(default='', max_length=3000)
    work_types: list[Literal['essay', 'connections', 'gaps', 'review', 'questions']] = Field(default_factory=lambda: ['essay'], max_length=5)

    @model_validator(mode='after')
    def unique_work_types(self):
        self.work_types = list(dict.fromkeys(self.work_types))
        if self.enabled and not self.work_types:
            raise ValueError('请至少选择一类研究任务')
        return self


class FindingAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['keep', 'dismiss', 'restore', 'done', 'again', 'remembered']


class ReadingPresence(BaseModel):
    client_id: str = Field(min_length=1, max_length=100)
    reading: bool
