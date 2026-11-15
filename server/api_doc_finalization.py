"""Finalize authored metadata after explicit overlays; never grant API authority."""
import copy
from api_doc_native_access import _path
from native_access_codec import wire_contract

METHODS = {'get', 'post', 'put', 'patch', 'delete'}


def finalize_documentation(original):
    schema = copy.deepcopy(original)
    wire = wire_contract()
    authored = {(item['method'].lower(), _path(item['path']))
                for item in wire['operations'] + wire['phoneOperations']}
    effective = {(method, path) for path, operations in schema['paths'].items()
                 for method in operations if method in METHODS}
    for method, path in sorted(effective & authored):
        schema['paths'][path][method]['x-wegoh-documentation'] = {
            'authoring': 'explicit-operation-contract',
            'review': 'Independent handler/consumer meaning review required; presence is not approval.',
            'source': 'Explicit native_access_wire and Native authorization overlay; runtime handler remains authoritative.'}
    # FastAPI's generated validation DTO is distinct from authentication failures.
    validation = schema.get('components', {}).get('schemas', {}).get('HTTPValidationError', {})
    detail = validation.get('properties', {}).get('detail')
    if detail is not None:
        detail['description'] = 'FastAPI가 요청 파라미터 형식 검증에 실패했을 때 반환하는 위치·메시지·오류 종류 목록입니다. 현재 인증·권한 거절이나 업무 오류의 성공 응답을 뜻하지 않습니다.'
    coverage = schema['x-wegoh-documentation-coverage']
    coverage.setdefault('genericCatalogOperations', coverage['operations'])
    coverage['authorizationOverlayOperations'] = len(effective & authored)
    coverage['operations'] = len(effective)
    coverage['keys'] = 'Final described HTTP operations after explicit overlays; generic catalog and authorization overlay counts remain separate provenance. Contract-only routes retain their availability markers.'
    return schema
