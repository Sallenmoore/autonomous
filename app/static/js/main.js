// === define a Global object to store all of my page-level variables:
var Global = {
  intervals: [],
  timer: 0,
  total: 0,
  paused: false,
};

function createIcon(name) {
  const icon = document.createElement("i");
  icon.classList.add("material-icons");
  icon.innerHTML = name;
  return icon;
}

//===My document.ready() handler...
document.addEventListener("DOMContentLoaded", () => {
  //=== do some code stuff...
  M.AutoInit();
  set_timer();
  _add_interval(0, 20);
  _add_interval(0, 10);
  //===finally, bind my events
  bindEvents();
});

//===This function handles event binding for anything on the page
//===Bind to existing functions, not anonymous functions

function bindEvents() {
  document.getElementById("total_time").addEventListener("change", set_timer);
  document.querySelectorAll("input[type='number']").forEach((element) => {
    element.addEventListener("change", (e) => {
      num = e.currentTarget.value.toString();
      while (num.length < 2) {
        num = "0" + num;
      }
      e.currentTarget.value = num;
    });
  });
  document
    .getElementById("add_interval_button")
    .addEventListener("click", add_interval);
  document
    .getElementById("start_button")
    .addEventListener("click", start_timer);
  document
    .getElementById("pause_button")
    .addEventListener("click", pause_timer);
  document.getElementById("clear_button").addEventListener("click", stop_timer);
  //it. It will apply those bindings dynamically.
}

//===Then everything below this is all of the other declared functions for my page...

function _add_interval(mins, secs) {
  Global.intervals.push(mins * 60 + secs);
  let new_interval = document.createElement("li");
  if (Global.intervals.length == 1) {
    new_interval.innerHTML = `${mins}:${secs} <i class="material-icons">chevron_left</i>`;
  } else {
    new_interval.innerHTML = `${mins}:${secs}`;
  }
  document.getElementById("intervals").appendChild(new_interval);
}

function add_interval(e) {
  _add_interval(
    document.getElementById("add_interval_min").value,
    document.getElementById("add_interval_sec").value
  );
}

function set_timer(e) {
  var minutes = document.getElementById("total_min").value;
  var seconds = document.getElementById("total_sec").value;
  document.getElementById("clock").innerHTML = minutes + " : " + seconds;
}

function pause_timer(e) {
  var pbutton = document.getElementById("pause_button");
  if (Global.paused) {
    Global.paused = false;
    pbutton.removeChild(pbutton.firstChild);
    pbutton.innerHTML = "PAUSE";
  } else {
    Global.paused = true;
    pbutton.removeChild(pbutton.firstChild);
    let icon = document.createElement("i");
    icon.className = "material-icons";
    icon.innerHTML = "pause";
    pbutton.append(icon);
  }
}

function stop_timer(e) {
  if (Global.timer) {
    clearInterval(Global.timer);
  }
  set_timer(e);
}

function start_timer(e) {
  Global.paused = false;
  if (Global.timer) {
    clearInterval(Global.timer);
  }
  // Time calculations for days, hours, minutes and seconds
  var minutes = document.getElementById("total_min").value;
  var seconds = document.getElementById("total_sec").value;

  var interval_index = 0;
  var countdown_total = Math.floor(minutes * 60) + (seconds % 60);

  // Update the count down every 1 second
  Global.timer = setInterval(function () {
    if (Global.paused) {
      return;
    }
    var minutes = Math.floor(countdown_total / 60);
    var seconds = countdown_total % 60;
    // Display the result in the element with id="clock"
    document.getElementById("clock").innerHTML = minutes + " : " + seconds;

    // If the count down is finished, write some text
    if (countdown_total <= 0) {
      clearInterval(Global.timer);
      document.getElementById("clock_msg").innerHTML = "SET COMPLETE";
    }

    if ((countdown_total + 1) % Global.intervals[interval_index] == 0) {
      document.getElementById("clock_msg").innerHTML = "INTERVAL COMPLETE";

      let intervals = document.getElementById("intervals");

      let li = intervals.children[interval_index];
      li.removeChild(li.querySelector("i"));

      interval_index = (interval_index + 1) % Global.intervals.length;

      intervals.children[interval_index].appendChild(
        createIcon("chevron_left")
      );
    } else if (countdown_total % 3 == 0) {
      document.getElementById("clock_msg").innerHTML = "";
    }
    countdown_total -= 1;
  }, 1000);
}
