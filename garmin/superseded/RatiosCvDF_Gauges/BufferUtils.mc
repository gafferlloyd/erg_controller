import Toybox.Lang;

class BufferUtils {

    // Push value, cap at maxSize. Returns the (possibly new) array — caller must reassign.
    // Array.remove(v) removes by VALUE not index, so we use slice() to drop the front.
    static function push(buf as Array, value as Object, maxSize as Number) as Array {
        buf.add(value);
        if (buf.size() > maxSize) {
            return buf.slice(1, null) as Array;
        }
        return buf;
    }

    static function mean(buf as Array) as Float {
        if (buf.size() == 0) { return 0.0; }
        var sum = 0.0;
        for (var i = 0; i < buf.size(); i++) { sum += buf[i]; }
        return sum / buf.size();
    }

    static function variance(buf as Array) as Float {
        if (buf.size() == 0) { return 0.0; }
        var m = BufferUtils.mean(buf);
        var v = 0.0;
        for (var i = 0; i < buf.size(); i++) {
            var d = buf[i] - m;
            v += d * d;
        }
        return v / buf.size();
    }

    static function ready(buf as Array, minSize as Number) as Boolean {
        return buf.size() >= minSize;
    }
}
