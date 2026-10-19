"""Onboarding wizard payloads (S-8.10.1)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OnboardingChoices(BaseModel):
    channels: list[str] = []
    first_job_id: str | None = None


class OnboardingState(BaseModel):
    step: int = 1
    choices: OnboardingChoices = OnboardingChoices()
    dismissed: bool = False
    started_at: str | None = None
    completed_at: str | None = None
    dismissed_at: str | None = None
    #: S-8.10.2: the jobs page's first-run checklist was hidden.
    checklist_dismissed: bool = False
    checklist_dismissed_at: str | None = None


class FirstJob(BaseModel):
    id: str
    job_type: str
    status: str
    has_report: bool


class OnboardingMilestones(BaseModel):
    jobs: int
    first_job: FirstJob | None = None
    report_opened: bool = False
    #: Questions asked on any surface (runs, the library, the history chat).
    questions: int = 0


class OnboardingResponse(BaseModel):
    onboarded_at: str | None = None
    state: OnboardingState
    started: bool = False
    milestones: OnboardingMilestones
    #: Whether `/` should send this account to `/welcome`.
    should_onboard: bool


class OnboardingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: int | None = Field(default=None, ge=1, le=3)
    channels: list[str] | None = Field(default=None, max_length=5)
    first_job_id: str | None = None
    completed: bool = False
    dismissed: bool = False
    #: Hide the jobs-page checklist (S-8.10.2). Does not start the wizard.
    checklist_dismissed: bool = False
