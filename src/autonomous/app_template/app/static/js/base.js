// === define a Global object to store all of my site-level variables:
var Global = {
  key: "value",
};

//========================================================================//
//  UTILITY FUNCTIONS                                                     //
//========================================================================//
function random_int(min, max) {
  min = Math.ceil(min);
  max = Math.floor(max);
  return Math.floor(Math.random() * (max - min+1) + min); // The maximum is exclusive and the minimum is inclusive
}

//======= Get Elements =======//
function get_class_elems(class_name) {
  return Array.from(document.getElementsByClassName(class_name));
}

function get_id(id) {
  return document.getElementById(id);
}

function outerHeight(el) {
  const style = getComputedStyle(el);

  return (
    el.getBoundingClientRect().height +
    parseFloat(style.marginTop) +
    parseFloat(style.marginBottom)
  );
}

//======= Attach Events =======//

function add_event(element, event, fn) {
  if (Array.isArray(element) || element instanceof NodeList) {
    element.forEach((el) => {
      el.addEventListener(event, fn);
    });
  } else {
    element.addEventListener(event, fn);
  }
}

function id_event(id, event, fn) {
  add_event(get_id(id), event, fn);
}

function class_event(class_name, event, fn) {
  get_class_elems(class_name).forEach((el) => {
    add_event(el, event, fn);
  });
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
function show(element) {
  if (Array.isArray(element) || element instanceof NodeList) {
    element.forEach((el) => {
      el.classList.remove("is-hidden");
    });
  } else {
    element.classList.remove("is-hidden");
  }
}

// Hide an element
function hide(element) {
  if (Array.isArray(element) || element instanceof NodeList) {
    element.forEach((el) => {
      el.classList.add("is-hidden");
    });
  } else {
    element.classList.add("is-hidden");
  }
}

// Toggle element visibility
function toggle(element) {
  if (Array.isArray(element) || element instanceof NodeList) {
    element.forEach((el) => {
      el.classList.toggle("is-hidden");
    });
  } else {
    element.classList.toggle("is-hidden");
  }
}

// =============== Intervals =============== //


// =============== Animations =============== //

function animate(obj) {
  obj.context.clearRect ( 0 , 0 , obj.boundaryX , obj.boundaryY );
  obj.draw();
  requestAnimationFrame(() => { animate(obj); });
}


// =============== Intervals =============== //

//================== Form ==================//
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
  fn = (response) => {
    console.log(response);
  }
) {
  fetch(url, {
    method: "POST", // *GET, POST, PUT, DELETE, etc.
    mode: "same-origin", // no-cors, *cors, same-origin
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(data), // body data type must match "Content-Type" header
  })
    .then((response) => {
      return response.json();
    })
    .then((data) => {
      fn(data);
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
