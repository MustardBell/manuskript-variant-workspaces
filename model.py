import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Optional


SCHEMA_VERSION = 1
MAX_MEMBERS = 5


class VariantDataError(ValueError):
    pass


class VariantRole(str, Enum):
    ORIGINAL = "original"
    TRANSLATION = "translation"
    REWRITE = "rewrite"
    COMPOSITE = "composite"
    ALTERNATE = "alternate"


class SyncMode(str, Enum):
    OFF = "off"
    PERCENTAGE = "percentage"
    PARAGRAPH = "paragraph"
    ANCHORS = "anchors"


def new_id(prefix):
    return "{}-{}".format(prefix, uuid.uuid4().hex)


@dataclass(frozen=True)
class VariantMember:
    id: str
    item_id: str
    label: str
    language: str = ""
    role: VariantRole = VariantRole.ALTERNATE
    parent_item_id: Optional[str] = None
    read_only: bool = True

    def __post_init__(self):
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "item_id", str(self.item_id))
        object.__setattr__(self, "label", str(self.label).strip())
        object.__setattr__(self, "language", str(self.language).strip())
        object.__setattr__(self, "role", VariantRole(self.role))
        if not self.id or not self.item_id or not self.label:
            raise VariantDataError(
                "Variant members require IDs, outline item IDs, and labels."
            )

    @classmethod
    def create(
            cls, item_id, label, language="",
            role=VariantRole.ALTERNATE, parent_item_id=None,
            read_only=True):
        return cls(
            id=new_id("member"),
            item_id=str(item_id),
            label=str(label),
            language=str(language),
            role=role,
            parent_item_id=parent_item_id,
            read_only=bool(read_only),
        )


@dataclass(frozen=True)
class AnchorPoint:
    paragraph_index: int
    paragraph_end_index: int
    offset_in_paragraph: int
    end_offset_in_paragraph: int
    approximate_offset: int
    fingerprint: str
    snippet: str

    def __post_init__(self):
        integer_fields = (
            "paragraph_index",
            "paragraph_end_index",
            "offset_in_paragraph",
            "end_offset_in_paragraph",
            "approximate_offset",
        )
        for name in integer_fields:
            value = int(getattr(self, name))
            if value < 0:
                raise VariantDataError(
                    "Anchor positions cannot be negative."
                )
            object.__setattr__(self, name, value)
        if self.paragraph_end_index < self.paragraph_index:
            raise VariantDataError(
                "An anchor range cannot end before it begins."
            )


@dataclass(frozen=True)
class AlignmentAnchor:
    id: str
    label: str
    points: Mapping[str, AnchorPoint]

    def __post_init__(self):
        object.__setattr__(self, "id", str(self.id))
        object.__setattr__(self, "label", str(self.label).strip())
        object.__setattr__(self, "points", dict(self.points))
        if not self.id or not self.label or len(self.points) < 2:
            raise VariantDataError(
                "Alignment anchors require a label and at least two panes."
            )

    @classmethod
    def create(cls, label, points):
        return cls(new_id("anchor"), label, points)


@dataclass(frozen=True)
class VariantGroup:
    id: str
    title: str
    canonical_member_id: str
    members: tuple
    anchors: tuple = ()

    def __post_init__(self):
        members = tuple(self.members)
        anchors = tuple(self.anchors)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "anchors", anchors)
        if not self.id or not str(self.title).strip():
            raise VariantDataError("Variant groups require an ID and title.")
        if not 1 <= len(members) <= MAX_MEMBERS:
            raise VariantDataError(
                "Variant groups require between one and five members."
            )
        member_ids = [member.id for member in members]
        item_ids = [member.item_id for member in members]
        if len(set(member_ids)) != len(member_ids):
            raise VariantDataError("Variant member IDs must be unique.")
        if len(set(item_ids)) != len(item_ids):
            raise VariantDataError(
                "An outline document can occur only once in a variant group."
            )
        if self.canonical_member_id not in member_ids:
            raise VariantDataError(
                "The canonical target must be a member of its group."
            )
        known = set(member_ids)
        for anchor in anchors:
            if not set(anchor.points).issubset(known):
                raise VariantDataError(
                    "Alignment anchors refer to an unknown member."
                )

    @classmethod
    def create(cls, title, members, canonical_member_id=None):
        members = tuple(members)
        if not members:
            raise VariantDataError("A new group requires at least one member.")
        return cls(
            id=new_id("group"),
            title=str(title),
            canonical_member_id=(
                canonical_member_id or members[0].id
            ),
            members=members,
        )

    @property
    def canonical_member(self):
        return next(
            member
            for member in self.members
            if member.id == self.canonical_member_id
        )

    def member(self, member_id):
        return next((
            member for member in self.members if member.id == member_id
        ), None)

    def with_member(self, member):
        if len(self.members) >= MAX_MEMBERS:
            raise VariantDataError("A group cannot contain more than five panes.")
        return replace(self, members=self.members + (member,))

    def update_member(self, member):
        if self.member(member.id) is None:
            raise KeyError(member.id)
        return replace(
            self,
            members=tuple(
                member if current.id == member.id else current
                for current in self.members
            ),
        )

    def without_member(self, member_id):
        remaining = tuple(
            member for member in self.members if member.id != member_id
        )
        if not remaining:
            raise VariantDataError(
                "Remove the group instead of its final member."
            )
        canonical = self.canonical_member_id
        if canonical == member_id:
            canonical = remaining[0].id
        anchors = tuple(
            replace(
                anchor,
                points={
                    key: value
                    for key, value in anchor.points.items()
                    if key != member_id
                },
            )
            for anchor in self.anchors
            if len(anchor.points) > 2 or member_id not in anchor.points
        )
        return replace(
            self,
            canonical_member_id=canonical,
            members=remaining,
            anchors=anchors,
        )

    def with_canonical(self, member_id):
        if self.member(member_id) is None:
            raise KeyError(member_id)
        return replace(self, canonical_member_id=member_id)

    def with_anchor(self, anchor):
        values = tuple(
            current
            for current in self.anchors
            if current.id != anchor.id
        ) + (anchor,)
        return replace(self, anchors=values)

    def without_anchor(self, anchor_id):
        return replace(
            self,
            anchors=tuple(
                anchor for anchor in self.anchors if anchor.id != anchor_id
            ),
        )


@dataclass(frozen=True)
class VariantState:
    groups: tuple = ()
    active_group_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        groups = tuple(self.groups)
        object.__setattr__(self, "groups", groups)
        if int(self.schema_version) != SCHEMA_VERSION:
            raise VariantDataError(
                "Unsupported variant data schema {}.".format(
                    self.schema_version
                )
            )
        group_ids = [group.id for group in groups]
        if len(set(group_ids)) != len(group_ids):
            raise VariantDataError("Variant group IDs must be unique.")
        item_owners = {}
        for group in groups:
            for member in group.members:
                owner = item_owners.get(member.item_id)
                if owner is not None and owner != group.id:
                    raise VariantDataError(
                        "An outline document cannot belong to multiple "
                        "scene families."
                    )
                item_owners[member.item_id] = group.id
        if (
            self.active_group_id is not None
            and self.active_group_id not in group_ids
        ):
            object.__setattr__(
                self,
                "active_group_id",
                group_ids[0] if group_ids else None,
            )

    def group(self, group_id):
        return next((group for group in self.groups if group.id == group_id), None)

    def upsert(self, group):
        found = self.group(group.id) is not None
        groups = tuple(
            group if current.id == group.id else current
            for current in self.groups
        )
        if not found:
            groups += (group,)
        return replace(
            self,
            groups=groups,
            active_group_id=group.id,
        )

    def remove(self, group_id):
        groups = tuple(group for group in self.groups if group.id != group_id)
        active = self.active_group_id
        if active == group_id:
            active = groups[0].id if groups else None
        return replace(self, groups=groups, active_group_id=active)


@dataclass(frozen=True)
class ComparisonState:
    group_id: str
    pane_order: tuple = ()
    sync_mode: SyncMode = SyncMode.PARAGRAPH
    proportional_sync: bool = False
    text_width: int = 560
    unlocked_member_ids: tuple = ()
    scroll_positions: Mapping[str, int] = field(default_factory=dict)
    cursor_positions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "pane_order", tuple(self.pane_order))
        object.__setattr__(
            self,
            "unlocked_member_ids",
            tuple(self.unlocked_member_ids),
        )
        object.__setattr__(self, "sync_mode", SyncMode(self.sync_mode))
        object.__setattr__(
            self,
            "proportional_sync",
            bool(self.proportional_sync),
        )
        object.__setattr__(self, "text_width", max(280, min(
            int(self.text_width), 1600
        )))
        object.__setattr__(self, "scroll_positions", {
            str(key): int(value)
            for key, value in self.scroll_positions.items()
        })
        object.__setattr__(self, "cursor_positions", {
            str(key): int(value)
            for key, value in self.cursor_positions.items()
        })


def anchor_point_to_dict(point):
    return {
        "paragraph_index": point.paragraph_index,
        "paragraph_end_index": point.paragraph_end_index,
        "offset_in_paragraph": point.offset_in_paragraph,
        "end_offset_in_paragraph": point.end_offset_in_paragraph,
        "approximate_offset": point.approximate_offset,
        "fingerprint": point.fingerprint,
        "snippet": point.snippet,
    }


def anchor_point_from_dict(value):
    return AnchorPoint(
        paragraph_index=value.get("paragraph_index", 0),
        paragraph_end_index=value.get(
            "paragraph_end_index",
            value.get("paragraph_index", 0),
        ),
        offset_in_paragraph=value.get("offset_in_paragraph", 0),
        end_offset_in_paragraph=value.get(
            "end_offset_in_paragraph",
            value.get("offset_in_paragraph", 0),
        ),
        approximate_offset=value.get("approximate_offset", 0),
        fingerprint=str(value.get("fingerprint", "")),
        snippet=str(value.get("snippet", "")),
    )


def state_to_dict(state):
    return {
        "schema_version": SCHEMA_VERSION,
        "active_group_id": state.active_group_id,
        "groups": [
            {
                "id": group.id,
                "title": group.title,
                "canonical_member_id": group.canonical_member_id,
                "members": [
                    {
                        "id": member.id,
                        "item_id": member.item_id,
                        "label": member.label,
                        "language": member.language,
                        "role": member.role.value,
                        "parent_item_id": member.parent_item_id,
                        "read_only": member.read_only,
                    }
                    for member in group.members
                ],
                "anchors": [
                    {
                        "id": anchor.id,
                        "label": anchor.label,
                        "points": {
                            key: anchor_point_to_dict(point)
                            for key, point in anchor.points.items()
                        },
                    }
                    for anchor in group.anchors
                ],
            }
            for group in state.groups
        ],
    }


def state_from_dict(value):
    if not isinstance(value, dict):
        raise VariantDataError("Variant data must be a JSON object.")
    groups = []
    for group_value in value.get("groups", ()):
        members = tuple(
            VariantMember(
                id=member["id"],
                item_id=member["item_id"],
                label=member["label"],
                language=member.get("language", ""),
                role=member.get("role", VariantRole.ALTERNATE.value),
                parent_item_id=member.get("parent_item_id"),
                read_only=member.get("read_only", True),
            )
            for member in group_value.get("members", ())
        )
        anchors = tuple(
            AlignmentAnchor(
                id=anchor["id"],
                label=anchor["label"],
                points={
                    key: anchor_point_from_dict(point)
                    for key, point in anchor.get("points", {}).items()
                },
            )
            for anchor in group_value.get("anchors", ())
        )
        groups.append(VariantGroup(
            id=group_value["id"],
            title=group_value["title"],
            canonical_member_id=group_value["canonical_member_id"],
            members=members,
            anchors=anchors,
        ))
    return VariantState(
        groups=tuple(groups),
        active_group_id=value.get("active_group_id"),
        schema_version=value.get("schema_version", SCHEMA_VERSION),
    )


def comparison_to_dict(state):
    return {
        "group_id": state.group_id,
        "pane_order": list(state.pane_order),
        "sync_mode": state.sync_mode.value,
        "proportional_sync": state.proportional_sync,
        "text_width": state.text_width,
        "unlocked_member_ids": list(state.unlocked_member_ids),
        "scroll_positions": dict(state.scroll_positions),
        "cursor_positions": dict(state.cursor_positions),
    }


def comparison_from_dict(value):
    return ComparisonState(
        group_id=str(value["group_id"]),
        pane_order=tuple(value.get("pane_order", ())),
        sync_mode=value.get("sync_mode", SyncMode.PARAGRAPH.value),
        proportional_sync=value.get("proportional_sync", False),
        text_width=value.get("text_width", 560),
        unlocked_member_ids=tuple(value.get("unlocked_member_ids", ())),
        scroll_positions=value.get("scroll_positions", {}),
        cursor_positions=value.get("cursor_positions", {}),
    )
