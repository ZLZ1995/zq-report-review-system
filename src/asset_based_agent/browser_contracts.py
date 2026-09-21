"""Shared browser proposals: data only, no host code or execution authority."""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_serializer, model_validator

from .agent_contracts import BrowserIntent, Identifier, Record, Versioned


class Choice(Record):
    id: str = Field(pattern=r'^[1-9][0-9]{0,2}$')
    text: str = Field(max_length=160)


class Control(Record):
    id: str = Field(pattern=r'^[1-9][0-9]{0,2}$')
    kind: Literal['button', 'link', 'textfield', 'select', 'file']
    text: str = Field(max_length=160)
    disabled: bool
    options: list[Choice] = Field(default_factory=list, max_length=100)


class RawObservation(Record):
    nonce: str = Field(min_length=1, max_length=128)
    origin: str = Field(max_length=2048)
    text: str = Field(max_length=12000)
    controls: list[Control] = Field(max_length=200)
    truncated: bool


class Observation(RawObservation):
    page_version: int = Field(ge=0, strict=True)
    untrusted: Literal[True] = True


class DownloadSummary(Record):
    name: str = Field(min_length=1, max_length=180, pattern=r'^[^/\\\x00]+$')
    size: int = Field(ge=0, strict=True)
    origin: str = Field(max_length=2048)


class UploadArtifact(Record):
    id: Identifier
    name: str = Field(min_length=1, max_length=180, pattern=r'^[^/\\\x00]+$')
    size: int = Field(ge=0, le=64 * 1024 * 1024, strict=True)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class BrowserStepRequest(Versioned):
    request_id: Identifier
    model_id: Identifier
    task_id: Identifier
    sequence: int = Field(ge=1, le=32, strict=True)
    goal: str = Field(min_length=1, max_length=12000)
    scope: BrowserIntent
    observation: Observation | None = None
    completed_downloads: list[DownloadSummary] = Field(default_factory=list, max_length=32)
    generated_downloads: bool = Field(default=False, strict=True)
    upload_artifacts: list[UploadArtifact] = Field(default_factory=list, max_length=32)

    @model_serializer(mode='wrap')
    def legacy_shape(self, handler):
        data = handler(self)
        if not self.completed_downloads:
            data.pop('completed_downloads', None)
        if not self.generated_downloads:
            data.pop('generated_downloads', None)
        if not self.upload_artifacts:
            data.pop('upload_artifacts', None)
        return data

    @model_validator(mode='after')
    def bounded(self):
        if self.generated_downloads and 'download' not in self.scope.actions:
            raise ValueError('Generated download outside task scope')
        if self.upload_artifacts and ('upload' not in self.scope.actions
                or len({a.id for a in self.upload_artifacts}) != len(self.upload_artifacts)):
            raise ValueError('Upload artifact list outside scope or ambiguous')
        if self.completed_downloads and ('download' not in self.scope.actions
                or any(item.origin not in self.scope.origins for item in self.completed_downloads)):
            raise ValueError('Download summary outside task scope')
        if not self.goal.strip() or len(self.model_dump_json().encode('utf-8')) > 64000:
            raise ValueError('Browser request exceeds bounds')
        if self.observation is not None:
            if self.observation.origin not in self.scope.origins:
                raise ValueError('Observation origin outside task scope')
            controls = self.observation.controls
            if len({c.id for c in controls}) != len(controls):
                raise ValueError('Duplicate observed targets')
            if any(len({o.id for o in c.options}) != len(c.options) for c in controls):
                raise ValueError('Duplicate observed options')
        return self


class BrowserStepProposal(Versioned):
    request_id: Identifier
    action: Literal['navigate', 'observe', 'click', 'fill', 'select', 'scroll', 'wait', 'login', 'download', 'upload', 'ask', 'finish']
    target: str = Field(default='', max_length=3)
    value: str = Field(default='', max_length=4000)
    url: str = Field(default='', max_length=2048)
    summary: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(default='', max_length=2000)
    artifact_id: str = Field(default='', max_length=128)
    object_label: str = Field(default='', max_length=512)

    @model_serializer(mode='wrap')
    def legacy_shape(self, handler):
        data = handler(self)
        for key in ('artifact_id', 'object_label'):
            if not data.get(key):
                data.pop(key, None)
        return data


def validate_browser_step(request, proposal):
    request = BrowserStepRequest.model_validate(request.model_dump())
    proposal = BrowserStepProposal.model_validate(proposal.model_dump())
    if proposal.request_id != request.request_id or not proposal.summary.strip():
        raise ValueError('Browser proposal identity mismatch')
    action = proposal.action
    if action == 'upload':
        if (proposal.artifact_id not in {a.id for a in request.upload_artifacts}
                or not proposal.object_label.strip() or any(ord(c) < 32 for c in proposal.object_label)):
            raise ValueError('Upload requires a listed artifact and explicit object')
    elif proposal.artifact_id or proposal.object_label:
        raise ValueError('Unexpected upload metadata')
    if action not in {'ask', 'finish'} and action not in request.scope.actions:
        raise ValueError('Browser action outside task scope')
    if action not in {'fill', 'select', 'scroll', 'wait'} and proposal.value:
        raise ValueError('Unexpected browser value')
    if action == 'login' and request.observation is None:
        raise ValueError('Saved login requires a current observation')
    if action in {'scroll', 'wait'}:
        if request.observation is None:
            raise ValueError('View action requires a current observation')
        if action == 'scroll' and proposal.value not in {'up', 'down'}:
            raise ValueError('Scroll requires one viewport direction')
        if action == 'wait' and (not proposal.value.isascii() or not proposal.value.isdigit()
                                or not 100 <= int(proposal.value) <= 5000):
            raise ValueError('Wait must be 100 to 5000 milliseconds')
    if action != 'navigate' and proposal.url:
        raise ValueError('Unexpected navigation URL')
    if action not in {'click', 'fill', 'select', 'download', 'upload'} and proposal.target:
        raise ValueError('Unexpected browser target')
    if action == 'navigate':
        parsed = urlsplit(proposal.url)
        if (not proposal.url or parsed.username is not None or parsed.password is not None
                or '\\' in proposal.url or any(c.isspace() or ord(c) < 32 for c in proposal.url)
                or f'{parsed.scheme}://{parsed.netloc}' not in request.scope.origins):
            raise ValueError('Navigation outside task scope')
    if action in {'click', 'fill', 'select', 'download', 'upload'}:
        observed = request.observation
        target = next((c for c in observed.controls if c.id == proposal.target), None) if observed else None
        if target is None or target.disabled:
            raise ValueError('Target absent or disabled')
        if (action == 'click' and target.kind not in {'button', 'link'}
                or action == 'download' and target.kind != 'link'
                    and not (request.generated_downloads and target.kind == 'button')
                or action == 'upload' and target.kind != 'file'
                or action == 'fill' and target.kind != 'textfield'
                or action == 'select' and (target.kind != 'select'
                    or proposal.value not in {o.id for o in target.options})):
            raise ValueError('Action does not match observed control')
    if action == 'finish' and (request.observation is None or not proposal.evidence.strip()
                              or proposal.evidence not in request.observation.text):
        raise ValueError('Completion proposal lacks observed evidence')
    # Even a grounded finish is only a proposal. The host verifies the task's
    # actual business acceptance criteria; dispatched/loaded is never success.
    return proposal
