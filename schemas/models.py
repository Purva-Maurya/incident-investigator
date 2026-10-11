from typing import Dict, List, Optional, Literal
from pydantic import BaseModel, Field

class FaultRecord(BaseModel):
    """Ground truth written by runner (never visible to the investigator)"""
    fault_id: str        #unique fault identifier 
    fault_type: str       # kind of fault 
    root_cause_service: str #service where the fault originated
    start_ts:float     #fault start time 
    end_ts:float        # fault end time 

class Anomaly(BaseModel):
    service: str
    metric: str                  # like db_pool_utilization 
    target: str = ""             #for edge metrics : service -> target  
    oneset_ts: float             # when there will be deactivation of the fault, the anomaly will be detected at this timestamp
    peak_ts: Optional[float] = None   # the timestamp when the anomaly reaches its peak 
    severity: float                   # recirds how unusual the metric was according to the detection method 
    baseline: float=0.0
    peak_value: float = 0.0
    method: str = "robust_z"

EvidenceType = Literal["anomaly", "lag_correlation", "trace", "saturation", "deploy_event", "dependency", "log_pattern"]

class Evidence(BaseModel):
    id: str 
    type: EvidenceType
    description: str
    service: str
    timestamp: Optional[float] = None
    strength: float = Field(ge=0, le=1)
    data: dict[str, float | str] = {}

class Candidate(BaseModel):
    service: str
    cause_type: str
    score: float
    confidence: float = 0.0
    supporting_evidence_ids: List[str]
    score_breakdown : Dict[str, float] = {}

class Investigation(BaseModel):
    """Everyting the RCA engine produced. The LLM sees Only this (never raw logs/metrics)."""   
    incident_id: str
    window_start_ts: float
    incident_ts: float
    trigger_metric: str
    anomalies: List[Anomaly]
    evidence: List[Evidence]
    candidates: List[Candidate]

class Claim(BaseModel):
    text: str
    evidence_ids: List[str]

class IncidentReport(BaseModel):
    incident_id: str
    headline: str
    root_cause: str
    root_cause_service: str
    root_cause_type: str
    claims: List[Claim]
    confidence: float 
    generated_by: str = "template"
