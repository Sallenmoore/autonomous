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
  bindEvents();
});

//===This function handles event binding for anything on the page
//===Bind to existing functions, not anonymous functions

function bindEvents() {}

//===Then everything below this is all of the other declared functions for my page...

function foo() {}
