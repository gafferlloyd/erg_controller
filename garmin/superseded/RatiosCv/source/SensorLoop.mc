import Toybox.Timer;
import Toybox.Sensor;
import Toybox.Lang;

// 1Hz timer that reads power + HR and feeds DataModel.
class SensorLoop {

    private var _timer  as Timer.Timer;
    private var _model  as DataModel;
    var elapsedSecs as Number = 0;

    function initialize(model as DataModel) {
        _model = model;
        _timer = new Timer.Timer();
    }

    function start() as Void {
        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE, Sensor.SENSOR_BIKECADENCE] as Array<Sensor.SensorType>);
        Sensor.enableSensorEvents(method(:onSensor));
        _timer.start(method(:onTick), 1000, true);
    }

    function stop() as Void {
        _timer.stop();
        Sensor.enableSensorEvents(null);
    }

    function onTick() as Void {
        elapsedSecs++;
        var info = Sensor.getInfo();
        var power = (info.power != null) ? info.power as Number : 0;
        var hr    = (info.heartRate != null) ? info.heartRate as Number : 0;
        if (power > 0 || hr > 0) {
            _model.tick(power, hr);
        }
        WatchUi.requestUpdate();
    }

    // Sensor event callback — updates are also pulled in onTick via getInfo()
    function onSensor(sensorInfo as Sensor.Info) as Void {
    }
}
