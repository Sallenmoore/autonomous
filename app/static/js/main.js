// === define a Global object to store all of my page-level variables:
var Global = {
  intervals: [],
  total: 0,
};

//===My document.ready() handler...
document.addEventListener("DOMContentLoaded", () => {
  //=== do some code stuff...
  M.AutoInit();
  //===finally, bind my events
  bindEvents();
});

//===This function handles event binding for anything on the page
//===Bind to existing functions, not anonymous functions

function bindEvents() {
  document
    .getElementById("add_interval_button")
    .addEventListener("click", add_interval);
  document
    .getElementById("start_button")
    .addEventListener("click", add_interval);
  document
    .getElementById("pause_button")
    .addEventListener("click", add_interval);
  document
    .getElementById("clear_button")
    .addEventListener("click", add_interval);
  //it. It will apply those bindings dynamically.
}

//===Then everything below this is all of the other declared functions for my page...
function add_interval(e) {
  let mins = document.getElementById("add_interval_min").value;
  let secs = document.getElementById("add_interval_sec").value;
  Global.intervals.push({ mins: mins, secs: secs });
  let new_interval = document.createElement("li");
  new_interval.innerHTML = `${mins}:${secs}`;
  document.getElementById("intervals").appendChild(new_interval);
}
