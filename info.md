# Integration for HeLau1337's SmartBed
This HomeAssistant integration is very specific to my own needs. I built a ESP8266 controller that sends signals to the motor that moves the upper and lower parts of my bed. This controller has a REST API, also created by myself.

## Adding the integration

...is currently only possible by editing the configuration.yaml:

```
cover:
  - platform: "smartbed"
    name: "My SmartBed"
    base_url: "http://esp-smartbed-controller.local"
    scan_interval: 20
```
