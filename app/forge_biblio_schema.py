from typing import Literal, Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationError


class EntrySchema(BaseModel):
    """Pydantic schema for bibliographic entries with strict validation."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    type: Literal["book", "paper", "url", "concept"] = Field(..., description="Type of bibliographic entry")
    title: str = Field(..., min_length=5, description="Title of the entry")
    authors: Optional[List[str]] = Field(None, description="List of authors")
    year: Optional[int] = Field(None, ge=1800, le=2030, description="Publication year")
    doi: Optional[str] = Field(None, description="Digital Object Identifier")
    url: Optional[str] = Field(None, description="URL to the resource")
    pdf_url: Optional[str] = Field(None, description="URL to the PDF resource")
    description: Optional[str] = Field(None, max_length=1000, description="Description of the entry")
    triggered_by_idea_id: str = Field(..., min_length=1, description="ID of the idea that triggered this entry")
    source_kind: Literal["human_paste", "agent_extract", "agent_research"] = Field(
        ..., description="Source of the bibliographic entry"
    )

    @field_validator("authors")
    @classmethod
    def validate_authors(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is not None and len(v) == 0:
            raise ValueError("authors list cannot be empty")
        return v

    @field_validator("url", "pdf_url")
    @classmethod
    def validate_urls(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("https://"):
            raise ValueError("URL must start with https://")
        return v


def validate_entry(d: dict) -> tuple[bool, str]:
    """
    Validate a dictionary against the EntrySchema.

    Args:
        d: Dictionary to validate

    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    try:
        EntrySchema(**d)
        return True, ""
    except ValidationError as e:
        return False, str(e)


def to_dict(entry: EntrySchema) -> dict:
    """
    Convert an EntrySchema instance to a dictionary for SQL serialization.

    Args:
        entry: Validated EntrySchema instance

    Returns:
        dict: Dictionary representation of the entry
    """
    return entry.model_dump()


if __name__ == "__main__":
    # Test cases
    print("Running tests...")

    # Valid cases
    valid_cases = [
        {
            "type": "book",
            "title": "The Art of Computer Programming",
            "authors": ["Donald Knuth"],
            "year": 1968,
            "doi": "10.1016/C2009-0-22554-7",
            "url": "https://www-cs-faculty.stanford.edu/~knuth/taocp.html",
            "triggered_by_idea_id": "idea123",
            "source_kind": "human_paste",
        },
        {
            "type": "paper",
            "title": "Attention Is All You Need",
            "authors": ["Vaswani", "Shazeer", "Parmar"],
            "year": 2017,
            "pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
            "triggered_by_idea_id": "idea456",
            "source_kind": "agent_extract",
        },
        {
            "type": "concept",
            "title": "Machine Learning Basics",
            "description": "Fundamental concepts of machine learning",
            "triggered_by_idea_id": "idea789",
            "source_kind": "agent_research",
        },
    ]

    for i, case in enumerate(valid_cases, 1):
        is_valid, error = validate_entry(case)
        assert is_valid, f"Valid case {i} failed: {error}"
        print(f"Valid case {i} passed")

    # Invalid cases
    invalid_cases = [
        (
            {
                "type": "book",
                "title": "Hi!",  # Too short (3 chars)
                "triggered_by_idea_id": "idea123",
                "source_kind": "human_paste",
            },
            "title",
        ),
        (
            {
                "type": "invalid_type",  # Invalid type
                "title": "Valid Title Here",
                "triggered_by_idea_id": "idea123",
                "source_kind": "human_paste",
            },
            "type",
        ),
        (
            {
                "type": "paper",
                "title": "Valid Title Here",
                "year": 1799,  # Year out of range
                "triggered_by_idea_id": "idea123",
                "source_kind": "human_paste",
            },
            "year",
        ),
        (
            {
                "type": "url",
                "title": "Valid Title Here",
                "url": "http://example.com",  # Not https
                "triggered_by_idea_id": "idea123",
                "source_kind": "human_paste",
            },
            "url",
        ),
        (
            {
                "type": "book",
                "title": "Valid Title Here",
                "description": "x" * 1001,  # Too long
                "triggered_by_idea_id": "idea123",
                "source_kind": "human_paste",
            },
            "description",
        ),
    ]

    for i, (case, expected_error) in enumerate(invalid_cases, 1):
        is_valid, error = validate_entry(case)
        assert not is_valid, f"Invalid case {i} should have failed"
        assert expected_error in error, f"Invalid case {i} error doesn't match: {error}"
        print(f"Invalid case {i} passed (correctly failed with {expected_error} error)")

    print("All tests passed!")
