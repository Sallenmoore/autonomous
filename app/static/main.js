//===My document.ready() handler...
document.addEventListener("DOMContentLoaded", () => {
  //=== do some code stuff...
  bindEvents();
});

//===This function handles event binding for anything on the page
//===Bind to existing functions, not anonymous functions

function bindEvents() {}

//===Then everything below this is all of the other declared functions...

function foo() {}

// === define a Global object to store all of my site-level variables:
var Global = {
  key: "value",
};

//========================================================================//
//  UTILITY FUNCTIONS                                                     //
//========================================================================//

function get_class(class_name) {
  return Array.from(document.getElementsByClassName(class_name));
}

//======= Get Elements =======//
function get_id(id) {
  return document.getElementById(id);
}

function addevent(element, event, fn) {
  if (Array.isArray(element)) {
    element.forEach((el) => {
      el.addEventListener(event, fn);
    });
  } else {
    element.addEventListener(event, fn);
  }
}
//======= Templates =======//

function get_template(selector) {
  return document
    .getElementById("js_templates")
    .querySelector(selector)
    .cloneNode(true);
}

//========= Display ===========//

// Show an element
function show(elem) {
  elem.classList.remove("is-hidden");
}

// Hide an element
function hide(elem) {
  elem.classList.add("is-hidden");
}

// Toggle element visibility
function toggle(elem, cssclass = "is-hidden") {
  return elem.classList.toggle("is-hidden");
}

// =============== Animations =============== //

// =============== Intervals =============== //

//============================================ Form ============================================//
function form_values(form) {
  let formData = new FormData(form);
  let data = {};
  formData.forEach(function (value, key) {
    if (value) data[key] = value;
  });
  return data;
}

function post_data(
  url = "#",
  data = {},
  form = null,
  fn = (response) => {
    console.log(response);
  }
) {
  if (form) {
    data = form_values(form);
  }
  fetch(url, {
    method: "POST", // *GET, POST, PUT, DELETE, etc.
    mode: "same-origin", // no-cors, *cors, same-origin
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data), // body data type must match "Content-Type" header
  })
    .then((response) => {
      fn(response);
    })
    .catch((error) => {
      console.log(error);
    });
}

// =============== Icons =============== //

// === Create an icon element
function createIcon(name) {
  const icon = document.createElement("i");
  icon.classList.add("material-icons");
  icon.innerHTML = name;
  return icon;
}

//==== Modals

//==== Tabs

//==== Tooltips

//==== Tags

//==== Popovers

//==== Dropdowns

//==== Collapsibles

//==== Accordions

//==== Carousels

//==== Progress Bar

