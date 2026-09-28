import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nsd/nsd.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

void main() {
  runApp(const ProviderScope(child: DeviceControlApp()));
}

class DeviceControlApp extends StatelessWidget {
  const DeviceControlApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Control app',
      theme: ThemeData.dark(useMaterial3: true),
      home: const DashboardScreen(),
    );
  }
}

class DashboardScreen extends ConsumerStatefulWidget {
  const DashboardScreen({super.key});

  @override
  ConsumerState<DashboardScreen> createState() => _DashboardScreenState();
}

class _DashboardScreenState extends ConsumerState<DashboardScreen> {
  Discovery? _discovery;
  WebSocketChannel? _channel;
  bool _isConnected = false;
  String _hostStatus = "Disconnected";
  
  String _lastTranscribedVoice = "Say 'Hey Jarvis, set volume to 40'";
  double _volume = 50;
  double _brightness = 50;

  //Connect
  @override
  void initState() {
    super.initState();
    _startDiscovery();
  }

  Future<void> _startDiscovery() async {
    try {
      _discovery = await startDiscovery('_appcontrol._tcp');
      _discovery!.addListener(() {
        for (var service in _discovery!.services) {
          if (service.host != null && service.port != null) {
            _connectToDaemon(service.host!, service.port!);
            stopDiscovery(_discovery!);
            break;
          }
        }
      });
    } catch (e) {
      setState(() => _hostStatus = "Discovery failed: $e");
    }
  }

  void _connectToDaemon(String host, int port) {
    final wsUrl = Uri.parse('ws://$host:$port/ws/control');
    try {
      _channel = WebSocketChannel.connect(wsUrl);
      setState(() {
        _isConnected = true;
        _hostStatus = "Connected to $host:$port";
      });

      _channel!.stream.listen((message) {
        final data = jsonDecode(message);
        
        // Handle voice transcriptions pushed from laptop daemon
        if (data['type'] == 'transcription') {
          setState(() {
            _lastTranscribedVoice = '"${data['text']}"';
          });
        } 
        // Sync sliders when daemon settings change via voice
        else if (data['type'] == 'status') {
          setState(() {
            if (data['action'] == 'set_volume') {
              _volume = (data['value'] as num).toDouble();
            } else if (data['action'] == 'set_brightness') {
              _brightness = (data['value'] as num).toDouble();
            }
          });
        }
      });
    } catch (e) {
      setState(() => _hostStatus = "Connection error: $e");
    }
  }
  //Disconnect

  //Comms
  void _sendCommand(String action, int value) {
    if (_channel != null && _isConnected) {
      _channel!.sink.add(jsonEncode({'action': action, 'value': value}));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text("AI Device & Voice Control")),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Card(
              color: _isConnected ? Colors.green.withValues(alpha: 0.2) : Colors.red.withValues(alpha: 0.2),
              child: ListTile(
                leading: Icon(_isConnected ? Icons.check_circle : Icons.error, color: _isConnected ? Colors.green : Colors.red),
                title: Text(_isConnected ? "Voice Bridge Active" : "Offline"),
                subtitle: Text(_hostStatus),
              ),
            ),
            const SizedBox(height: 24),
            
            // Voice Activity Card
            Card(
              elevation: 4,
              color: Colors.blueGrey.shade900,
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Row(
                  children: [
                    const Icon(Icons.mic, color: Colors.cyanAccent, size: 32),
                    const SizedBox(width: 16),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text("Latest Voice Command", style: TextStyle(color: Colors.grey, fontSize: 12)),
                          const SizedBox(height: 4),
                          Text(_lastTranscribedVoice, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w500)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),

            // Controls
            ElevatedButton(
              onPressed: () {
                _connectToDaemon("192.168.254.248", 8000);
              }, 
              child: const Text("Connect via direct IP link")),
            Text("System Volume (${_volume.round()}%)", style: const TextStyle(fontWeight: FontWeight.bold)),
            Slider(
              value: _volume,
              min: 0,
              max: 100,
              onChanged: (val) {
                setState(() => _volume = val);
                if ( val.round() % 10 == 0) {
                  _sendCommand("set_volume", val.round());
                }
              },
            ),
            const SizedBox(height: 16),
            Text("Screen Brightness (${_brightness.round()}%)", style: const TextStyle(fontWeight: FontWeight.bold)),
            Slider(
              value: _brightness,
              min: 0,
              max: 100,
              onChanged: (val) {
                setState(() => _brightness = val);
                if ( val.round() % 10 == 0) {
                  _sendCommand("set_brightness", val.round());
                }
              },
            ),
          ],
        ),
      ),
    );
  }
}
//Comms