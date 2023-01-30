//=== define a Global object to store all of my page-level variables:
var Global = {
  currentId: undefined,
  action: "create",
  user: "Kevin",
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
  // setup your bindings one time, when the page loads and then forget about
  //it. It will apply those bindings dynamically.
}

//===Then everything below this is all of the other declared functions for my page...
function function_action() {
  console.log("Did stuff");
}
