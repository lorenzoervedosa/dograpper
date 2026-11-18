"""Manifest management and generation."""

import os
import json
import hashlib
import logging
from dataclasses import dataclass, asdict, field, fields
from typing import Dict, Optional
from datetime import datetime, timezone
from urllib.parse import urlparse

from ..utils.redact import recordable_url
from .ignore_parser import DOGRAPPER_STATE_NAMES

logger = logging.getLogger(__name__)

@dataclass
class ManifestEntry:
    # URL dograpper requested for the file; None when no run recorded one (see build_manifest).
    url: Optional[str]
    size_bytes: int
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    # Filesystem-relative path (relative to output_dir). Optional for backwards
    # compatibility; when absent, fall back to the entry key.
    local_path: Optional[str] = None
    mtime: Optional[float] = None
    # md5 of the file's bytes. Optional for backwards compatibility: entries
    # loaded from a manifest written before this field existed have it as
    # None, and diff_manifests falls back to the old size+mtime comparison
    # for those specifically.
    content_hash: Optional[str] = None

@dataclass
class Manifest:
    base_url: str
    last_run: str
    files: Dict[str, ManifestEntry]

_ENTRY_FIELDS = {f.name for f in fields(ManifestEntry)}


def read_manifest(path: str) -> Manifest:
    """Read a manifest, tolerating unknown fields from older versions.

    Raises OSError, ValueError (bad JSON or encoding), TypeError or
    AttributeError (wrong shape) when the file cannot be loaded.
    """
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    files = {}
    for k, v in data.get('files', {}).items():
        # Drop any fields the current dataclass doesn't know about so we
        # stay forward/backwards compatible with manifest schema changes.
        payload = {kk: vv for kk, vv in v.items() if kk in _ENTRY_FIELDS}
        files[k] = ManifestEntry(**payload)

    return Manifest(
        base_url=data.get('base_url', ''),
        last_run=data.get('last_run', ''),
        files=files
    )


def load_manifest(path: str) -> Optional[Manifest]:
    """Load manifest from disk; a missing or unreadable file reads as None."""
    if not os.path.exists(path):
        return None

    try:
        return read_manifest(path)
    except Exception as e:
        logger.warning(f"Failed to parse manifest at {path}, treating as missing: {e}")
        return None

def save_manifest(manifest: Manifest, path: str) -> None:
    """Save manifest to disk."""
    d = asdict(manifest)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save manifest to {path}: {e}")

def build_manifest(base_url: str, output_dir: str,
                   fetched: Optional[Dict[str, str]] = None,
                   previous: Optional[Manifest] = None,
                   manifest_path: Optional[str] = None) -> Manifest:
    """Build a manifest based on the output directory contents.

    Keys are URL-relative paths (the path component the file would have on the
    original site) so the JSON shape matches the spec in about_dograpper.md.
    The on-disk location — which typically includes the ``<netloc>`` directory
    created by wget — is preserved in ``local_path`` so callers can still find
    the file when re-running.

    ``url`` comes from ``fetched``: saved file path, as the downloader reported
    it, -> URL requested for it, without userinfo. A URL whose query has a
    parameter off the navigation allowlist is recorded as None
    (recordable_url). A file not in ``fetched`` keeps the URL ``previous``
    recorded for the same local_path, if any. The saved path is never turned back into a URL:
    ``--adjust-extension``'s ``.html``, ``index.html`` for a directory URL, a
    dropped or decoded query and httrack's renaming all make one saved name
    stand for several URLs.

    The manifest at ``manifest_path`` and dograpper's state files are left out.
    """
    files = {}
    last_run = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    parsed_base = urlparse(base_url)
    netloc = parsed_base.netloc
    real_output = os.path.realpath(output_dir)
    urls = {os.path.relpath(os.path.realpath(path), real_output).replace(os.sep, '/'):
            recordable_url(url) for path, url in (fetched or {}).items()}
    recorded = {(e.local_path or k): e.url for k, e in previous.files.items()} if previous else {}
    own = os.path.realpath(manifest_path) if manifest_path else None

    for root, _, filenames in os.walk(output_dir):
        for f in filenames:
            full_path = os.path.join(root, f)
            if f.lower() in DOGRAPPER_STATE_NAMES or os.path.realpath(full_path) == own:
                continue
            fs_rel = os.path.relpath(full_path, output_dir).replace(os.sep, '/')
            size = os.path.getsize(full_path)

            with open(full_path, 'rb') as fh:
                content_hash = hashlib.md5(fh.read()).hexdigest()

            # Strip the leading "<netloc>/" that wget adds so the key matches
            # the URL path on the original site.
            if netloc and (fs_rel == netloc or fs_rel.startswith(netloc + '/')):
                url_rel = fs_rel[len(netloc):].lstrip('/')
            else:
                url_rel = fs_rel

            key = url_rel or fs_rel

            mtime = os.path.getmtime(full_path)

            files[key] = ManifestEntry(
                url=urls[fs_rel] if fs_rel in urls else recorded.get(fs_rel),
                size_bytes=size,
                etag=None,
                last_modified=None,
                local_path=fs_rel,
                mtime=mtime,
                content_hash=content_hash,
            )

    return Manifest(
        base_url=base_url,
        last_run=last_run,
        files=files
    )

def merge_manifests(old: Optional[Manifest], new: Manifest) -> Manifest:
    """Merge newly generated manifest with the previous one, preserving etags and discarding absent files."""
    if not old:
        return new
        
    merged_files = {}
    for key, new_entry in new.files.items():
        if key in old.files:
            old_entry = old.files[key]
            # Keep old etag if size didn't change
            if old_entry.size_bytes == new_entry.size_bytes:
                new_entry.etag = old_entry.etag
                new_entry.last_modified = old_entry.last_modified
        merged_files[key] = new_entry
        
    return Manifest(
        base_url=new.base_url,
        last_run=new.last_run,
        files=merged_files
    )


@dataclass
class ManifestDiff:
    added: list
    modified: list
    removed: list


def narrow_diff_to_paths(diff: ManifestDiff, manifest: Manifest,
                         rel_paths) -> ManifestDiff:
    """Narrow *diff* to the files a pack run would actually include.

    Manifest keys are URL-relative (wget's ``<netloc>/`` prefix stripped),
    so ``local_path`` is what maps them back onto the filesystem-relative
    paths the caller works with. Removals are always kept: a file that
    disappeared changes the output even though it can no longer be matched
    against the current file list.
    """
    rel_paths = set(rel_paths)

    def _kept(key: str) -> bool:
        entry = manifest.files.get(key)
        local = (entry.local_path or key) if entry else key
        return local in rel_paths

    return ManifestDiff(
        added=[k for k in diff.added if _kept(k)],
        modified=[k for k in diff.modified if _kept(k)],
        removed=list(diff.removed),
    )


def diff_manifests(old: Optional[Manifest], new: Manifest) -> ManifestDiff:
    """Compare two manifests and return the differences."""
    if old is None:
        return ManifestDiff(
            added=list(new.files.keys()),
            modified=[],
            removed=[],
        )

    added = []
    modified = []
    removed = []

    for key, new_entry in new.files.items():
        if key not in old.files:
            added.append(key)
        else:
            old_entry = old.files[key]
            if old_entry.size_bytes != new_entry.size_bytes:
                modified.append(key)
            elif old_entry.mtime == new_entry.mtime:
                # Fast path: mtime unchanged, content assumed unchanged
                # without hashing.
                pass
            elif old_entry.content_hash is not None and new_entry.content_hash is not None:
                # mtime changed but content hash is available on both sides:
                # trust the hash, not the mtime (touch, cp without -p, a
                # fresh git clone all churn mtime without changing bytes).
                if old_entry.content_hash != new_entry.content_hash:
                    modified.append(key)
            else:
                # Backward compat: old_entry came from a manifest written
                # before content_hash existed. Can't verify by hash, so fall
                # back to the old size+mtime heuristic for this entry only.
                modified.append(key)

    for key in old.files:
        if key not in new.files:
            removed.append(key)

    return ManifestDiff(added=added, modified=modified, removed=removed)
