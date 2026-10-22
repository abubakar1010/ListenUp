"""Input and output formats of the Text AI tasks (Architecture 7.3, NFR-AI-4, FR-BL-13).

Every provider must return exactly these structures, and the gateway validates them before
use. The overall score and level of a gist are not here: our code computes them from the
dimension scores and the rubric weights (Architecture 5.4), never from model arithmetic.
`ai/prompts/<task>/schema.json` is the JSON Schema of the model named here; a test fails
when they differ. The input models bound what may reach a provider at every level: a
key point id is a short label (`kp1`), not a database id, and no model has room for an
account identifier.
"""

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Stable keys (Architecture 7.3). Callers pass `load_task(name)`, never a literal version.
EXTRACT_KEY_POINTS = "extract_key_points"
GRADE_GIST = "grade_gist"
SHADOW_FEEDBACK = "shadow_feedback"


class _Output(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


# --- extract_key_points (FR-BL-6; 3 to 6 points, the main idea first) ----------------


class ExtractedKeyPoint(_Output):
    text: str = Field(min_length=3, max_length=300)
    kind: Literal["main", "supporting"]


class KeyPoints(_Output):
    key_points: tuple[ExtractedKeyPoint, ...] = Field(min_length=3, max_length=6)

    @model_validator(mode="after")
    def _main_first(self) -> Self:
        kinds = [point.kind for point in self.key_points]
        if kinds[0] != "main" or kinds.count("main") != 1:
            raise ValueError("exactly one main idea, listed first")
        return self


# --- grade_gist (FR-BL-7 to FR-BL-9; rubric in SRS 5.2.1) ----------------------------


class DimensionScores(_Output):
    main_idea: int = Field(ge=0, le=100, strict=True)
    key_details: int = Field(ge=0, le=100, strict=True)
    accuracy: int = Field(ge=0, le=100, strict=True)


class GistGrade(_Output):
    dimension_scores: DimensionScores
    # Ids of the input key points the gist covers; our code checks them against the input.
    covered_points: tuple[str, ...] = Field(max_length=6)
    wrong_claims: tuple[str, ...] = Field(max_length=5)
    feedback: str = Field(min_length=1, max_length=1500)

    @model_validator(mode="after")
    def _unique_points(self) -> Self:
        if len(set(self.covered_points)) != len(self.covered_points):
            raise ValueError("duplicate covered point")
        return self


# --- shadow_feedback (FR-SH-11; measures and flagged words only, no audio) ------------


class ShadowFeedback(_Output):
    feedback: str = Field(min_length=1, max_length=600)
    top_fixes: tuple[str, ...] = Field(min_length=1, max_length=3)


# --- Inputs (FR-BL-13: only the transcript, key points, gist and round measures) ------


class _Input(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


_Text = Annotated[str, Field(strict=True)]


class KeyPointInput(_Input):
    id: _Text = Field(pattern=r"^kp[1-6]$")  # a label, never a stored id
    text: _Text = Field(max_length=300)
    kind: Literal["main", "supporting"]


class ExtractKeyPointsInput(_Input):
    transcript: _Text


class GradeGistInput(_Input):
    key_points: tuple[KeyPointInput, ...] = Field(min_length=1, max_length=6)
    transcript: _Text
    gist: _Text

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        if len({point.id for point in self.key_points}) != len(self.key_points):
            raise ValueError("duplicate key point id")
        return self


# The seven speaking measures (SRS 5.6, Database Design `round_grades.measures`).
Measure = Literal[
    "timing", "pronunciation", "accent", "articulation", "fluency", "fillers", "completeness"
]


class ShadowFeedbackInput(_Input):
    round: int = Field(ge=1, le=3, strict=True)
    measures: dict[Measure, Annotated[int, Field(ge=0, le=100, strict=True)]]
    flagged_words: tuple[Annotated[str, Field(strict=True, min_length=1, max_length=64)], ...]


TASK_INPUTS: dict[str, type[BaseModel]] = {
    EXTRACT_KEY_POINTS: ExtractKeyPointsInput,
    GRADE_GIST: GradeGistInput,
    SHADOW_FEEDBACK: ShadowFeedbackInput,
}

TASK_MODELS: dict[str, type[BaseModel]] = {
    EXTRACT_KEY_POINTS: KeyPoints,
    GRADE_GIST: GistGrade,
    SHADOW_FEEDBACK: ShadowFeedback,
}

# Small valid outputs. The fake Text AI returns these for the three tasks, so local runs
# and tests that do not register a response still get a schema-valid result.
EXAMPLES: dict[str, dict[str, Any]] = {
    EXTRACT_KEY_POINTS: {
        "key_points": [
            {"text": "The speaker explains why sleep matters.", "kind": "main"},
            {"text": "Adults need about eight hours.", "kind": "supporting"},
            {"text": "Screens late at night make sleep worse.", "kind": "supporting"},
        ]
    },
    GRADE_GIST: {
        "dimension_scores": {"main_idea": 80, "key_details": 60, "accuracy": 100},
        "covered_points": ["kp1"],
        "wrong_claims": [],
        "feedback": "You caught the main idea. You missed the part about screens.",
    },
    SHADOW_FEEDBACK: {
        "feedback": "Your pace was close to the speaker. Work on the ends of words.",
        "top_fixes": ["Say the final sound of 'asked'."],
    },
}
