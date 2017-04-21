var express = require('express');
var fs = require('fs');
var ini = require('ini')
var expandHomeDir = require('expand-home-dir')
var path = require('path');
var spawn = require('child_process').spawn;
var proc;

// connect, message and disconnect are built-in socket.io event names
var socket_event_connect = 'connect'
var socket_event_disconnect = 'disconnect'
var socket_event_gps = 'gps'				// to browser, provide gps state
var socket_event_imageReady = 'imageReady'		// to browser, notify that image available
var socket_event_status = 'vnavsStatus'			// to browser, provide vnavs state
var socket_event_startStream = 'startStream'		// from browser, request to start getting notifications
var socket_event_take_pic = 'takePic'			// from browser, operate camera
var socket_event_move_forward = 'moveForward'		// from browser, move forward
var socket_event_move_slow = 'moveSlow'			// from browser, move slow
var socket_event_move_reverse = 'moveReverse'		// from browser, move backward
var socket_event_move_stop = 'moveStop'			// from browser, move stop
var socket_event_steer = 'steer'
var mqtt = require('mqtt')
var mqtt_topic_take_pic = 'cameraman/orders'
var mqtt_topic_drive = 'helmsman/orders'

var config_fn = expandHomeDir('~/vnavs.ini')
var config = ini.parse(fs.readFileSync(config_fn, 'utf-8'))
var mqtt_broker = 'mqtt://' + config.MqttBroker.Host
var mqttc  = mqtt.connect(mqtt_broker)

mqttc.on('connect', function () {
  mqttc.subscribe('engineer_1/status')
  mqttc.subscribe('cameraman/pic_ready')
})
 
mqttc.on('message', function (topic, message) {
    if (topic === 'engineer_1/status') {
        io.sockets.emit(socket_event_gps, message.toString());
        //  mqttc.end()
    }
    if (topic === 'cameraman/pic_ready') {
        payload = JSON.parse(message);
        fn = payload['filename'];
        console.log("image ready", fn);
        io.sockets.emit(socket_event_imageReady, path.join(image_subdir, fn));
    }
})

var image_subdir = '/images'
var image_path = image_subdir + '/single.jpg'
var image_fqn = '/home/pi/projects/vnavs' + image_path
var static_subdir = '/node_root'


var app = express();
var http = require('http').Server(app);
app.set('view engine', 'pug')
var bodyParser = require('body-parser')
var urlencodedParser = bodyParser.urlencoded({ extended: false })
app.use(image_subdir, express.static(path.join('/bot1', image_subdir)));
var formTimeout = 3

app.get('/', function(req, res) {
  // res.sendFile(__dirname + static_subdir + '/index.html');
  res.render(__dirname + static_subdir + '/index.pug', {timeout: formTimeout });
});
app.post('/parms', urlencodedParser, function (req, res) {
  if (!req.body) return res.sendStatus(400)
  formTimeout = req.body.timeout
  res.render(__dirname + static_subdir + '/index.pug', {timeout: formTimeout });
});

var sockets = {};

var io = require('socket.io')(http);
io.on('connection', function(socket) {
  sockets[socket.id] = socket;
  console.log("Total clients connected : ", Object.keys(sockets).length);
  socket.on(socket_event_disconnect, function() {
    delete sockets[socket.id];
    // no more sockets, kill the stream
    if (Object.keys(sockets).length == 0) {
      app.set('watchingFile', false);
      if (proc) proc.kill();
      fs.unwatchFile(image_fqn);
    }
  });
  socket.on(socket_event_startStream, function() {
    startStreaming(io);
  });
  socket.on(socket_event_take_pic, function() {
    console.log("take pic");
    mqttc.publish(mqtt_topic_take_pic, '{"loopMode": "single", "loopFormat": "jpeg", "loopPublish": "file", "captureMode": "single", "captureFormat": "jpeg", "capturePublish": "file"}')
  });
  socket.on(socket_event_move_forward, function() {
    console.log("forward");
    mqttc.publish(mqtt_topic_drive, '{"speed": "f"}')
  });
  socket.on(socket_event_move_slow, function() {
    console.log("forward");
    mqttc.publish(mqtt_topic_drive, '{"speed": "d"}')
  });
  socket.on(socket_event_move_reverse, function() {
    console.log("reverse");
    mqttc.publish(mqtt_topic_drive, '{"speed": "r"}')
  });
  socket.on(socket_event_move_stop, function() {
    console.log("stop");
    mqttc.publish(mqtt_topic_drive, '{"speed": "s"}')
  });
  socket.on(socket_event_steer, function(heading) {
    console.log("steer " + heading);
    mqttc.publish(mqtt_topic_drive, JSON.stringify({"heading": heading}))
  });
  socket.on('helmsman', function(pkey, pval) {
    console.log("helmsman", pkey, pval);
    var payload = {};
    payload[pkey] = pval;
    mqttc.publish('helmsman/orders', JSON.stringify(payload))
  });
  socket.on('waypC', function() {
    mqttc.publish('navigator/waypoint', '{"request": "C"}')
  });
  socket.on('waypM', function() {
    mqttc.publish('navigator/waypoint', '{"request": "M"}')
  });
  socket.on('modeM', function() {
    mqttc.publish('navigator/mode', '{"mode": "M"}')
  });
  socket.on('modeG', function() {
    mqttc.publish('navigator/mode', '{"mode": "G"}')
  });
});

http.listen(3000, function() {
  console.log('listening on *:3000');
});

function stopStreaming() {
  if (Object.keys(sockets).length == 0) {
    app.set('watchingFile', false);
    if (proc) proc.kill();
    fs.unwatchFile(image_fqn);
  }
}

function startStreaming(io) {
  if (app.get('watchingFile')) {
    io.sockets.emit(socket_event_imageReady, image_path + '?_t=' + (Math.random() * 100000));
    return;
  }

  //var args = ["-vf", "-w", "640", "-h", "480", "-o", "./stream/image_stream.jpg", "-t", "999999999", "-tl", "100"];
  //proc = spawn('raspistill', args);
  console.log('Watching for changes...');
  app.set('watchingFile', true);
  fs.watchFile(image_fqn, function(current, previous) {
    io.sockets.emit(socket_event_imageReady, image_path + '?_t=' + (Math.random() * 100000));
  })
}
