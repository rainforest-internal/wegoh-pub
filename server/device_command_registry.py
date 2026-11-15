"""Fixed vehicle request contracts; capabilities never register executable actions."""
import math

SEATS = ('ROW_1_LEFT','ROW_1_CENTER','ROW_1_RIGHT','ROW_2_LEFT','ROW_2_CENTER','ROW_2_RIGHT','ROW_3_LEFT','ROW_3_CENTER','ROW_3_RIGHT')
WINDOWS = ('ROW_1_LEFT','ROW_1_RIGHT','ROW_2_LEFT','ROW_2_RIGHT')
# Remote control never targets the driver seat or window. Pleos Vehicle SDK 2.3.2 exposes no
# driver-side API, so the left-hand-drive driver position is fixed (same as the vehicle app).
DRIVER_AREA = 'ROW_1_LEFT'
# The only reason a vehicle may attach to a `rejected` ACK: it refused the request because the car is moving.
DRIVING_RESTRICTED = 'driving-restricted'

class ClimateAction:
    def __init__(self, identifier, label, kind, property_name):
        self.id,self.display_label,self.argument_kind,self.property_name=identifier,label,kind,property_name
        self.area_key=('seat'if kind in ('hvac-celsius','hvac-fan','seat-switch','seat-level')
                       else'window'if kind=='window-position'else None)

    def validate_arguments(self,value):
        fields={'value'}|({self.area_key}if self.area_key else set())
        if type(value)is not dict or set(value)!=fields:return False
        if self.area_key:
            areas=SEATS if self.area_key=='seat'else WINDOWS
            if (type(value[self.area_key])is not str or value[self.area_key]not in areas
                or value[self.area_key]==DRIVER_AREA):return False
        number=value['value']
        if self.argument_kind=='hvac-celsius':
            return type(number)in(int,float) and 0<=number<=50 and math.isfinite(number)
        if self.argument_kind in ('hvac-fan','window-position'):
            return type(number)is int and 0<=number<=100
        if self.argument_kind=='seat-level':
            return type(number)is int and 0<=number<=10
        return self.argument_kind in ('seat-switch','switch') and type(number)is bool

    def validate_ack(self,stage,evidence,context):
        if stage=='rejected':return type(evidence)is dict and evidence in ({},{'reason':DRIVING_RESTRICTED})
        if stage in ('received','unknown'):return type(evidence)is dict and evidence=={}
        if stage not in ('sdk-accepted','state-confirmed'):return False
        fields={'kind','requestId','property','value'}|({self.area_key}if self.area_key else set())
        if stage=='state-confirmed':fields|={'receivedAtElapsedMillis','capturedAtMillis'}
        if type(evidence)is not dict or set(evidence)!=fields:return False
        if evidence['kind']!=('pleos-vehicle-setter-v1'if stage=='sdk-accepted'else'pleos-vehicle-getter-v1'):return False
        arguments=context.get('arguments')
        if (evidence['requestId']!=context['requestId'] or evidence['property']!=self.property_name
            or not self.validate_arguments(arguments)
            or (self.area_key and evidence[self.area_key]!=arguments[self.area_key])
            or evidence['value']!=arguments['value']):return False
        if self.argument_kind in ('hvac-celsius','hvac-fan'):
            if type(evidence['value'])is bool:return False
        elif type(evidence['value'])is not type(arguments['value']):return False
        return stage=='sdk-accepted' or (type(evidence['receivedAtElapsedMillis'])is int
            and evidence['receivedAtElapsedMillis']>=0 and evidence['capturedAtMillis']is None)

class ProductionCommandRegistry:
    _actions=(ClimateAction('hvac.temperature','설정 온도','hvac-celsius','TARGET_CELSIUS'),
              ClimateAction('hvac.fan','풍량','hvac-fan','FAN_LEVEL'),
              ClimateAction('hvac.power','공조 전원','seat-switch','GLOBAL_POWER'),
              ClimateAction('hvac.ac','에어컨','seat-switch','AC'),
              ClimateAction('hvac.air_cleaner','공기청정','seat-switch','AIR_CLEANER'),
              ClimateAction('seat.heat','시트 열선','seat-level','SEAT_HEAT'),
              ClimateAction('seat.ventilation','시트 통풍','seat-level','SEAT_VENTILATION'),
              ClimateAction('window.position','창문 열림','window-position','WINDOW_POSITION'),
              ClimateAction('light.cabin','실내등','switch','CABIN_LIGHT'),
              ClimateAction('light.reading','독서등','seat-switch','READING_LIGHT'),
              ClimateAction('light.ambient','무드등','seat-switch','AMBIENT_LIGHT'))
    def describe(self):
        return [dict(id=a.id,revision=1)for a in self._actions]

    def lookup(self, capability_id, revision):
        return next((a for a in self._actions if a.id==capability_id),None)if type(revision)is int and revision==1 else None
