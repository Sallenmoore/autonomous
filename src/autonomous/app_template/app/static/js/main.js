//===My document.ready() handler...
document.addEventListener("DOMContentLoaded", () => {
  //=== Initialize widgets
  
  var mm = new MobileMenu();
  var ag = new AnimatedGraph(hover_msg="Getting a website doesn't have to be complicated");
  
  //=== do some code stuff...

  //--Set up events
  bindEvents();
});

//===This function handles event binding for anything on the page
//===Bind to existing functions, not anonymous functions

function bindEvents() {
  window.onscroll = function () {
    if (window.pageYOffset >= document.querySelector(".top").offsetTop ) {
      document.querySelector(".top").classList.add("is-static");
    } else {
      document.querySelector(".top").classList.remove("is-static");
    }
  }

  document.getElementById("generate-template").addEventListener("submit", (event) => { 
    event.preventDefault();
    let tempates_form = document.getElementById("generate-template");
    let values = form_values(tempates_form);
    let loader = document.querySelector('.is-loading');
    let templates = document.getElementById("generated_images");
    show(loader);
    hide(templates);
    post_data("/tpgenerate", values, (response) => {
      let img_urls = response['result'];
      console.log(img_urls)
      for (let img_col of templates.children) {
        img_col.querySelector("img").src = img_urls.shift();
      }
      hide(loader);
      show(templates);
      window.scrollTo(0, document.body.scrollHeight);
    });
  });

}

//===Then everything below this is all of the other declared functions...

function foo() {}
