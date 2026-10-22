"""Version 1 dataset and threshold contracts; no calibration defaults."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from listenup.ai.policy import CallContext
from listenup.ai.tasks import GradeGistInput

Suite = Literal["gist", "shadow"]
Level = Literal["Needs work", "Fair", "Good", "Excellent"]
Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
GIST_DIMENSIONS = frozenset({"main_idea", "key_details", "accuracy"})
SHADOW_MEASURES = frozenset(
    {"timing", "pronunciation", "accent", "articulation", "fluency", "fillers", "completeness"}
)


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Grade(Contract):
    scores: dict[str, Score] = Field(min_length=1)
    overall: Score
    level: Level | None = None
    filler_count: int | None = Field(default=None, ge=0, strict=True)


class ShadowInput(Contract):
    # Local paths resolved by the future scoring service, never downloaded by the runner.
    recording: str = Field(min_length=1)
    reference_audio: str = Field(min_length=1)
    reference_text: str = Field(min_length=1)


class Case(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    smoke: bool = False
    tags: tuple[str, ...] = ()
    input: GradeGistInput | ShadowInput
    context: CallContext = CallContext()
    expected: Grade
    # Synthetic Shadow report-contract samples only; never used for inference.
    synthetic_runs: tuple[Grade, Grade, Grade] | None = None


class Dataset(Contract):
    version: Literal[1]
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    kind: Literal["synthetic", "teacher"]
    suite: Suite
    source: str = Field(min_length=1)
    cases: tuple[Case, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_cases(self) -> Self:
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("duplicate case id")
        names = GIST_DIMENSIONS if self.suite == "gist" else SHADOW_MEASURES
        for case in self.cases:
            if (self.suite == "gist") != isinstance(case.input, GradeGistInput):
                raise ValueError("case input does not match suite")
            grades = (case.expected, *(case.synthetic_runs or ()))
            if any(set(grade.scores) != names for grade in grades):
                raise ValueError("grade must contain every dimension or measure exactly once")
            if self.suite == "gist" and case.expected.level is None:
                raise ValueError("gist requires an expected level")
            if self.suite == "shadow" and any(g.filler_count is None for g in grades):
                raise ValueError("Shadow requires filler counts")
            if case.synthetic_runs is not None and (
                self.kind != "synthetic" or self.suite != "shadow"
            ):
                raise ValueError("only synthetic Shadow permits report-contract samples")
        return self


class Rule(Contract):
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def one_bound(self) -> Self:
        if (self.min is None) == (self.max is None):
            raise ValueError("a threshold requires exactly one of min or max")
        return self


class Thresholds(Contract):
    version: Literal[1]
    scope: Literal["synthetic", "teacher"]
    # Empty rules mean uncalibrated and cannot produce PASS.
    rules: dict[Suite, dict[str, Rule]]
    # Operator-supplied score boundaries; no invented production level cutoffs.
    gist_level_bounds: tuple[Score, Score, Score] | None = None

    @model_validator(mode="after")
    def ordered_bounds(self) -> Self:
        if self.gist_level_bounds is not None:
            a, b, c = self.gist_level_bounds
            if not a < b < c:
                raise ValueError("level boundaries must be strictly increasing")
        return self
