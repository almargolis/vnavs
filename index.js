var express = require('express');
var fs = require('fs');
var path = require('path');
var spawn = require('child_process').spawn;
var proc;

var mqtt_broker = 'mqtt://192.168.8.101'
var mqtt = require('mqtt')
var mqttc  = mqtt.connect(mqtt_broker)
var mqtt_topic_take_pic = 'take_pic'
var mqtt_topic_take_pic = 'take_pic'
var mqtt_topic_set_speed = 'set_speed'
var mqtt_topic_steer = 'steer'
 
//mqttc.on('connect', function () {
//  mqttc.subscribe('presence')
//  mqttc.publish('presence', 'Hello mqtt')
//})
 
//mqttc.on('message', function (topic, message) {
  // message is Buffer 
//  console.log(message.toString())
//  mqttc.end()
//})

var image_subdir = '/temp'
var image_path = image_subdir + '/single.jpg'
var image_fqn = '/home/pi/projects/vnavs' + image_path
var static_subdir = '/node_root'

// connect, message and disconnect are built-in socket.io event names
var socket_event_connect = 'connect'
var socket_event_disconnect = 'disconnect'
var socket_event_imageReady = 'imageReady'		// to browser, notify that image available
var socket_event_status = 'vnavsStatus'			// to browser, provide vnavs state
var socket_event_startStream = 'startStream'		// from browser, request to start getting notifications
var socket_event_take_pic = 'takePic'			// from browser, operate camera
var socket_event_move_forward = 'moveForward'		// from browser, move forward
var socket_event_move_stop = 'moveStop'			// from browser, move stop
var socket_event_steer_straight = 'steerStraight'
var socket_event_steer_right = 'steerRight'
var socket_event_steer_left = 'steerLeft'

var app = express();
var http = require('http').Server(app);
var io = require('socket.io')(http);
app.use('/', express.static(path.join(__dirname, static_subdir)));
app.use(image_subdir, express.static(path.join(__dirname, image_subdir)));

app.get('/', function(req, res) {
  res.sendFile(__dirname + static_subdir + '/index.html');
});

var sockets = {};

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
  socket.on(socket_event_move_forward, function() {
    console.log("forward");
    mqttc.publish(mqtt_topic_set_speed, 'f')
  });
  socket.on(socket_event_move_stop, function() {
    mqttc.publish(mqtt_topic_set_speed, 's')
  });
  socket.on(socket_event_take_pic, function() {
    mqttc.publish(mqtt_topic_take_pic, 'now')
  });
  socket.on(socket_event_steer_straight, function() {
    mqttc.publish(mqtt_topic_steer, 's')
  });
  socket.on(socket_event_steer_left, function() {
    mqttc.publish(mqtt_topic_steer, '+l')
  });
  socket.on(socket_event_steer_right, function() {
    mqttc.publish(mqtt_topic_steer, '+r')
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
