from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RequestedComponent(BaseModel):
    service_role: str = Field(min_length=3, max_length=100)
    repository: str = Field(min_length=3, max_length=200, pattern=r"^[^/\s]+/[^/\s]+$")
    version: str = Field(min_length=1, max_length=100)
    tag: str = Field(min_length=2, max_length=100, pattern=r"^v[0-9A-Za-z][0-9A-Za-z._-]*$")
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{40}$")


class RegistrationRequest(BaseModel):
    participation_kind: Literal["tester", "sponsor", "both"]
    test_mode: Literal["offline", "online", "both"]
    platform: Literal["windows", "macos", "linux", "mixed"]
    experience: Literal["user", "developer", "security", "accessibility", "sponsor"]
    signer_name: str = Field(min_length=2, max_length=120)
    contact_consent: bool = False
    privacy_consent: bool
    beta_and_no_warranty: bool
    installation_and_operation_responsibility: bool
    background_services: bool
    backup_and_data_loss: bool
    release_license: bool
    electronic_signature: bool
    legal_capacity_and_authority: bool
    terms_version: str = Field(min_length=1, max_length=100)
    terms_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    privacy_version: str = Field(min_length=1, max_length=100)
    requested_components: list[RequestedComponent] = Field(default_factory=list, min_length=3, max_length=3)

    @field_validator(
        "privacy_consent",
        "beta_and_no_warranty",
        "installation_and_operation_responsibility",
        "background_services",
        "backup_and_data_loss",
        "release_license",
        "electronic_signature",
        "legal_capacity_and_authority",
    )
    @classmethod
    def require_acceptance(cls, value: bool) -> bool:
        if not value:
            raise ValueError("all required beta terms and risk acknowledgements must be accepted")
        return value


class CheckoutRequest(BaseModel):
    release_tag: str = Field(min_length=2, max_length=100, pattern=r"^v[0-9A-Za-z][0-9A-Za-z._-]*$")
    asset_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    license_accepted: bool
    integrity_acknowledged: bool
    operation_responsibility_acknowledged: bool
    data_loss_acknowledged: bool

    @field_validator(
        "license_accepted",
        "integrity_acknowledged",
        "operation_responsibility_acknowledged",
        "data_loss_acknowledged",
    )
    @classmethod
    def require_acknowledgement(cls, value: bool) -> bool:
        if not value:
            raise ValueError("release license, integrity, operation, and data-loss acknowledgements are required")
        return value


class DeletionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class BranchProvisionItem(BaseModel):
    repository: str = Field(min_length=3, max_length=200, pattern=r"^[^/\s]+/[^/\s]+$")
    branch_name: str = Field(min_length=7, max_length=200)
    commit_sha: str = Field(pattern=r"^[0-9a-fA-F]{40}$")
    status: Literal["provisioned", "declined", "retired"] = "provisioned"


class BranchProvisionRequest(BaseModel):
    installation_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    branches: list[BranchProvisionItem] = Field(min_length=1, max_length=4)
