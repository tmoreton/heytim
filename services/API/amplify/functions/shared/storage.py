from __future__ import annotations

from typing import Any


def object_version_identifiers(
    s3_client: Any,
    bucket_name: str,
    prefix: str,
    *,
    exact_keys: set[str] | None = None,
) -> list[dict[str, str]]:
    paginator = s3_client.get_paginator("list_object_versions")
    versions = []
    for page in paginator.paginate(
        Bucket=bucket_name,
        Prefix=prefix,
        PaginationConfig={"PageSize": 1000},
    ):
        for item in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]:
            key = item.get("Key")
            version_id = item.get("VersionId")
            if (
                isinstance(key, str)
                and isinstance(version_id, str)
                and (exact_keys is None or key in exact_keys)
            ):
                versions.append({"Key": key, "VersionId": version_id})
    return versions


def delete_object_version_identifiers(
    s3_client: Any,
    bucket_name: str,
    versions: list[dict[str, str]],
    *,
    resource_label: str,
) -> int:
    unique = {(item["Key"], item["VersionId"]): item for item in versions}
    objects = list(unique.values())
    for offset in range(0, len(objects), 1000):
        result = s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={"Objects": objects[offset : offset + 1000], "Quiet": True},
        )
        errors = result.get("Errors", [])
        if errors:
            raise RuntimeError(
                f"S3 did not delete {len(errors)} {resource_label} versions"
            )
    return len(objects)


def delete_object_versions(
    s3_client: Any,
    bucket_name: str,
    prefix: str,
    *,
    resource_label: str,
) -> int:
    """Delete every current version and delete marker below one owned prefix."""
    versions = object_version_identifiers(s3_client, bucket_name, prefix)
    return delete_object_version_identifiers(
        s3_client,
        bucket_name,
        versions,
        resource_label=resource_label,
    )
