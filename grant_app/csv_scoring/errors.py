"""Stable exceptions exposed by the CSV scoring boundary."""


class ScoringError(Exception):
    """Base class for expected CSV scoring failures."""


class CsvValidationError(ScoringError):
    """The uploaded CSV does not meet validation requirements."""


class UploadNotFoundError(ScoringError):
    """The requested upload does not exist."""


class JobNotFoundError(ScoringError):
    """The requested scoring job does not exist."""


class ModelUnavailableError(ScoringError):
    """The configured scoring model cannot be loaded or used."""
