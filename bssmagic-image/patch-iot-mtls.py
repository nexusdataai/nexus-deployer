"""Patch IoT listener to use mTLS instead of SigV4 for cross-account EKS deployments."""

TARGET = '/controller/build/services/iot-listener.service.js'

OLD = (
    'const builder = iot.AwsIotMqtt5ClientConfigBuilder'
    '.newWebsocketMqttBuilderWithSigv4Auth(this.config.ats, {\n'
    '                region: this.config.region,\n'
    '            });'
)

NEW = (
    'const { existsSync: _existsSync } = await import("node:fs");\n'
    '            let builder;\n'
    '            if (_existsSync("/tmp/cert.pem") && _existsSync("/tmp/private.key")) {\n'
    '                this.logger.info("Using mTLS authentication with X.509 certificates");\n'
    '                builder = iot.AwsIotMqtt5ClientConfigBuilder'
    '.newDirectMqttBuilderWithMtlsFromPath(\n'
    '                    this.config.ats, "/tmp/cert.pem", "/tmp/private.key");\n'
    '            } else {\n'
    '                this.logger.info("Falling back to SigV4 WebSocket authentication");\n'
    '                builder = iot.AwsIotMqtt5ClientConfigBuilder'
    '.newWebsocketMqttBuilderWithSigv4Auth(\n'
    '                    this.config.ats, { region: this.config.region });\n'
    '            }'
)

with open(TARGET) as f:
    code = f.read()

if OLD not in code:
    if 'newDirectMqttBuilderWithMtlsFromPath' in code:
        print('Already patched')
    else:
        raise SystemExit(f'ERROR: Could not find SigV4 pattern in {TARGET}')
else:
    code = code.replace(OLD, NEW)
    with open(TARGET, 'w') as f:
        f.write(code)
    print(f'Patched {TARGET}: SigV4 -> mTLS with X.509 fallback')
