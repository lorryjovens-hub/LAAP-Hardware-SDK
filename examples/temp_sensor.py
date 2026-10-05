"""LAAP Hardware 示例：智能温湿度传感器

一个虚拟的 ESP32 温湿度传感器，接入 LAAP 后可以让 LAAP 感知环境。
"""
import asyncio
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "python-sdk"))

from laap_hardware import LAAPDevice


class TempSensor(LAAPDevice):
    """温湿度传感器设备"""

    def __init__(self):
        super().__init__(
            device_id="temp-sensor-001",
            name="温湿度传感器",
            device_type="sensor",
            firmware_version="1.0.0",
        )
        self.add_capability("sensor.temperature")
        self.add_capability("sensor.humidity")

        self.add_tool(
            "sensor.read_temperature",
            self.read_temperature,
            "读取温度",
            {"type": "object", "properties": {}},
        )
        self.add_tool(
            "sensor.read_humidity",
            self.read_humidity,
            "读取湿度",
            {"type": "object", "properties": {}},
        )

    def read_temperature(self, args):
        return {"temperature": round(22.5 + random.uniform(-2, 2), 1), "unit": "°C"}

    def read_humidity(self, args):
        return {"humidity": round(55.0 + random.uniform(-5, 5), 1), "unit": "%"}


async def main():
    device = TempSensor()
    print(f"设备: {device.name}")
    print(f"能力: {device.capabilities}")
    print(f"工具: {[t['name'] for t in device.tools.list_tools()]}")
    print()
    print("演示工具调用:")
    print("  温度:", device.tools.call("sensor.read_temperature", {}))
    print("  湿度:", device.tools.call("sensor.read_humidity", {}))


if __name__ == "__main__":
    asyncio.run(main())