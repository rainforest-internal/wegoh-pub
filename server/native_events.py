"""Device event resource visibility; no second socket, queue or token format."""
BASE_DEVICE_RESOURCES = {'courses', 'playlists', 'devices'}
BROWSER_RESOURCES = BASE_DEVICE_RESOURCES | {'friends', 'rooms', 'history', 'vehicle'}


def visible_resources(auth, actor):
    if not actor.get('deviceId'):
        result = set(BROWSER_RESOURCES) | ({'content'} if actor.get('role') == 'admin' else set())
        service = getattr(auth, 'recommendation_service', None)
        if service and service.enabled:
            result.add('recommendations')
        cautions=getattr(auth,'cautions_service',None)
        if cautions and cautions.enabled:
            result.add('cautions')
        return result
    access = getattr(auth, 'native_access', None)
    if access is None:
        return set(BASE_DEVICE_RESOURCES)
    permissions = access.current(actor)['permissions']
    result = BASE_DEVICE_RESOURCES | {name for name, allowed in permissions.items() if allowed}
    vehicle = getattr(auth, 'vehicle_service', None)
    if vehicle and vehicle.enabled and vehicle.visible_to_device(actor):
        result.add('vehicle')
    return result
