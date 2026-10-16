"""Exceptions expressed in application language rather than vendor language."""


class PosterAgentError(Exception):
    """Base class for expected application errors."""


class ConfigurationError(PosterAgentError):
    """Runtime configuration is incomplete or invalid."""


class BriefLoadError(PosterAgentError):
    """The campaign brief cannot be read or decoded."""


class StrategyGenerationError(PosterAgentError):
    """The strategy provider could not generate a usable result."""


class ModelOutputError(StrategyGenerationError):
    """The provider responded, but no valid structured result was available."""


class PersistenceError(PosterAgentError):
    """An application artifact could not be persisted."""


class BrandKnowledgeError(PosterAgentError):
    """Brand knowledge cannot be ingested or retrieved safely."""


class BrandKnowledgeNotFound(BrandKnowledgeError):
    """No indexed brand profile exists for the requested tenant and brand."""


class RenderError(PosterAgentError):
    """A Sprint 3 rendering operation could not complete safely."""


class AssetValidationError(RenderError):
    """The approved visual asset set is missing, unsafe, or out of scope."""


class ImageGenerationError(RenderError):
    """The image provider did not return a usable background image."""
