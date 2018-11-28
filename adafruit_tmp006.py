# The MIT License (MIT)
#
# Copyright (c) 2018 Carter Nelson for Adafruit Industries
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
"""
`adafruit_tmp006`
====================================================

CircuitPython driver for the TMP006 contactless IR thermometer.

* Author(s): Carter Nelson

Implementation Notes
--------------------

**Hardware:**

 * `TMP006 Contact-less Infrared Thermopile Sensor <https://www.adafruit.com/product/1296>`_

**Software and Dependencies:**

* Adafruit CircuitPython firmware for the supported boards:
  https://github.com/adafruit/circuitpython/releases

 * Adafruit's Bus Device library: https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
"""

import time
import struct
from micropython import const
from adafruit_bus_device.i2c_device import I2CDevice

__version__ = "0.0.0-auto.0"
__repo__ = "https://github.com/adafruit/Adafruit_CircuitPython_TMP006.git"

# Default device I2C address.
_TMP006_I2CADDR = const(0x40)

# Register addresses.
_TMP006_VOBJ = const(0x00)
_TMP006_TAMB = const(0x01)
_TMP006_CONFIG = const(0x02)
_TMP006_MANUID = const(0xFE)
_TMP006_DEVID = const(0xFF)

# Config register values.
_TMP006_CFG_RESET = const(0x8000)
_TMP006_CFG_MODEON = const(0x7000)
CFG_1SAMPLE = const(0x0000)
CFG_2SAMPLE = const(0x0200)
CFG_4SAMPLE = const(0x0400)
CFG_8SAMPLE = const(0x0600)
CFG_16SAMPLE = const(0x0800)
_TMP006_CFG_DRDYEN = const(0x0100)
_TMP006_CFG_DRDY = const(0x0080)

class TMP006:
    # Class-level buffer for reading and writing data with the sensor.
    # This reduces memory allocations but means the code is not re-entrant or
    # thread safe!
    _BUFFER = bytearray(4)

    def __init__(self, i2c, address=_TMP006_I2CADDR, samplerate=CFG_16SAMPLE):
        self._device = I2CDevice(i2c, address)
        self._write_u16(_TMP006_CONFIG, _TMP006_CFG_RESET)
        time.sleep(.5)
        if samplerate not in (CFG_1SAMPLE, CFG_2SAMPLE, CFG_4SAMPLE, CFG_8SAMPLE,
                              CFG_16SAMPLE):
            raise ValueError('Unexpected samplerate value! Must be one of: ' \
                'CFG_1SAMPLE, CFG_2SAMPLE, CFG_4SAMPLE, CFG_8SAMPLE, or CFG_16SAMPLE')
        # Set configuration register to turn on chip, enable data ready output,
        # and start sampling at the specified rate.
        config = _TMP006_CFG_MODEON | _TMP006_CFG_DRDYEN | samplerate
        self._write_u16(_TMP006_CONFIG, config)
        # Check device ID match expected value.
        dev_id = self.read_register(_TMP006_DEVID)
        if dev_id != 0x67:
            raise RuntimeError('Init failed - Did not find TMP006')



    @property
    def active(self):
        """True if sensor is active."""
        return self._read_u16(_TMP006_CONFIG) & _TMP006_CFG_MODEON != 0

    @active.setter
    def active(self, val):
        if val:
            self._wake()
        else:
            self._sleep()

    @property
    def temperature(self):
        # pylint: disable=bad-whitespace, invalid-name, too-many-locals
        """Read object temperature from TMP006 sensor."""
        if not self.active:
            raise RuntimeError('Can not read from sensor when inactive.')
        while not self._data_ready():
            pass
        vobj = self.read_register(_TMP006_VOBJ)
        vobj = bytearray((vobj & 0xFF, vobj >> 8 & 0xFF))
        vobj = struct.unpack("<h", vobj)[0]
        vobj = vobj * 156.25e-9  # volts
        tamb = self.read_register(_TMP006_TAMB)
        tamb = bytearray((tamb & 0xFF, tamb >> 8 & 0xFF))
        tamb = struct.unpack("<h", tamb)[0]
        tamb = (tamb >> 2) / 32.
        tamb += 273.15 # kelvin
        # see TMP006 User Guide, section 5.1
        S0 = 6.4e-14 # nominal value
        a1 = 1.75e-3
        a2 = -1.678e-5
        TREF = 298.15
        b0 = -2.94e-5
        b1 = -5.7e-7
        b2 = 4.63e-9
        c2 = 13.4

        S = S0 * (1 + a1*(tamb - TREF) + a2*(tamb - TREF)**2)
        VOS = b0 + b1*(tamb - TREF) + b2*(tamb - TREF)**2
        fVOBJ = (vobj - VOS) + c2*(vobj - VOS)**2

        TOBJ = (tamb**4 + (fVOBJ/S))**0.25

        TOBJ -= 273.15 # back to celsius

        return TOBJ

    def _sleep(self):
        """Put TMP006 into low power sleep mode.  No measurement data will be
        updated while in sleep mode.
        """
        control = self._read_u16(_TMP006_CONFIG)
        control &= ~(_TMP006_CFG_MODEON)
        self._write_u16(_TMP006_CONFIG, control)

    def _wake(self):
        """Wake up TMP006 from low power sleep mode."""
        control = self._read_u16(_TMP006_CONFIG)
        control |= _TMP006_CFG_MODEON
        self._write_u16(_TMP006_CONFIG, control)
    def _data_ready(self):
        return (self.read_register(_TMP006_CONFIG) & _TMP006_CFG_DRDY) != 0

    def read_register(self, register):
        """Read sensor Register."""
        return  self._read_u16(register)

    def _read_u16(self, address):
        with self._device as i2c:
            self._BUFFER[0] = address & 0xFF
            i2c.write(self._BUFFER, end=1, stop=False)
            i2c.readinto(self._BUFFER, end=2)
        return self._BUFFER[0]<<8 | self._BUFFER[1]

    def _write_u16(self, address, val):
        with self._device as i2c:
            self._BUFFER[0] = address & 0xFF
            self._BUFFER[1] = (val >> 8) & 0xFF
            self._BUFFER[2] = val & 0xFF
            i2c.write(self._BUFFER, end=3)
