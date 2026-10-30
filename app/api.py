"""The three endpoints of the contract, plus /health.

Handlers never wait for the AI or the provider. Processing problems show up in
the request status, not in the HTTP code.
"""

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from models import RequestRecord, Status

router = APIRouter()


class CreateRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=2_000)


class CreatedResponse(BaseModel):
    id: str


class StatusResponse(BaseModel):
    id: str
    status: Status


def _find(request: Request, request_id: str) -> RequestRecord:
    record = request.app.state.store.get(request_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")
    return record


@router.post("/v1/requests", response_model=CreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_request(body: CreateRequest, request: Request) -> RequestRecord:
    return request.app.state.store.create(body.user_input)


@router.post("/v1/requests/{request_id}/process", response_model=StatusResponse, status_code=status.HTTP_202_ACCEPTED)
async def process_request(request_id: str, request: Request) -> RequestRecord:
    record = _find(request, request_id)
    request.app.state.pipeline.submit(record)
    return record


@router.get("/v1/requests/{request_id}", response_model=StatusResponse)
async def get_request(request_id: str, request: Request) -> RequestRecord:
    return _find(request, request_id)


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "requests": request.app.state.store.counts(),
        "metrics": request.app.state.pipeline.metrics(),
    }
