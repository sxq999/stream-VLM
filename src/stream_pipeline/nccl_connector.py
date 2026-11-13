"""Audit wrapper around the unmodified vLLM 0.11 NCCL connector.

Only imported by the optional GPU engine plugin loader. No transport algorithm
or tensor layout is changed. A GPU buffer handed to NCCL is NOT proof of
physical GPU-direct DMA; NCCL topology/SHM logs are separate evidence.
"""
import importlib.metadata
import hashlib
import json
import time
from vllm.distributed.kv_transfer.kv_connector.v1.p2p.p2p_nccl_connector import P2pNcclConnector
from vllm.logger import init_logger

logger=init_logger('vllm.stream_pipeline.nccl_connector')

class AuditedP2pNcclConnector(P2pNcclConnector):
    def __init__(self,*args,**kwargs):
        if importlib.metadata.version('vllm')!='0.11.0':
            raise RuntimeError('AuditedP2pNcclConnector is pinned to vLLM 0.11.0')
        super().__init__(*args,**kwargs)
        engine=self.p2p_nccl_engine
        if engine is not None:
            checksums=bool(self.config.get_from_extra_config('audit_checksums',False))
            def checksum(tensor):
                import torch
                return hashlib.sha256(tensor.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes()).hexdigest()
            original_send_tensor=engine.send_tensor
            def send_tensor(tensor_id,tensor,remote_address=None):
                if checksums:
                    logger.info('STREAM_KV_AUDIT %s',json.dumps(dict(event='kv_send_checksum',tensor_id=tensor_id,sha256=checksum(tensor))))
                return original_send_tensor(tensor_id,tensor,remote_address)
            engine.send_tensor=send_tensor
            original_send,original_recv=engine.send,engine.recv
            def send(comm,tensor,dst,stream=None):
                start=time.perf_counter();result=original_send(comm,tensor,dst,stream)
                logger.info('STREAM_KV_AUDIT %s',json.dumps(dict(event='nccl_send_complete',bytes=tensor.numel()*tensor.element_size(),device=str(tensor.device),duration_s=time.perf_counter()-start)))
                return result
            def recv(comm,tensor,src,stream=None):
                start=time.perf_counter();result=original_recv(comm,tensor,src,stream)
                logger.info('STREAM_KV_AUDIT %s',json.dumps(dict(event='nccl_recv_complete',bytes=tensor.numel()*tensor.element_size(),device=str(tensor.device),duration_s=time.perf_counter()-start)))
                return result
            engine.send,engine.recv=send,recv
            original_recv_tensor=engine.recv_tensor
            def recv_tensor(tensor_id,remote_address=None):
                value=original_recv_tensor(tensor_id,remote_address)
                if value is None:
                    raise RuntimeError('NCCL KV tensor missing; refusing silent cache fallback')
                if checksums:
                    logger.info('STREAM_KV_AUDIT %s',json.dumps(dict(event='kv_recv_checksum',tensor_id=tensor_id,sha256=checksum(value))))
                logger.info('STREAM_KV_AUDIT %s',json.dumps(dict(event='kv_tensor_available',tensor_id=tensor_id,bytes=value.numel()*value.element_size(),device=str(value.device))))
                return value
            engine.recv_tensor=recv_tensor

    def start_load_kv(self,forward_context,**kwargs):
        if self.is_producer or forward_context.attn_metadata is None:
            return super().start_load_kv(forward_context,**kwargs)
        meta=self._get_connector_metadata()
        requests=list(meta.requests) if meta is not None else []
        result=super().start_load_kv(forward_context,**kwargs)
        if not self.is_producer:
            for r in requests:
                logger.info('STREAM_KV_AUDIT %s',json.dumps(dict(event='request_kv_injected',request_id=r.request_id,tokens=r.num_tokens)))
        return result
