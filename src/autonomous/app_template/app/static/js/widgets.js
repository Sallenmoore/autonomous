//==== Progress Bar
class MobileMenu {
  constructor(menu_items_id = "nav-links", menu_toggle_id = "burger") {
    //#nav-links
    var slideout_menu = document.getElementById("slideout-menu");

    var menu_button = document.getElementById(menu_toggle_id);

    menu_button.addEventListener("click", () => {
      menu_button.classList.toggle("is-active");
      menuclose_button.classList.toggle("is-active");
      slideout_menu.classList.toggle("menu-open");
    });

    var menuclose_button = document.getElementById("slideoutmenu-close");

    menuclose_button.addEventListener("click", () => {
      menu_button.classList.toggle("is-active");
      menuclose_button.classList.toggle("is-active");
      slideout_menu.classList.toggle("menu-open");
    });
  }
}

//==== Modals
class Modal {}
//==== Tabs
class Tab {}
//==== Tooltips
class Tooltip {}
//==== Tags
class Tag {}
//==== Popovers
class Popover {}
//==== Dropdowns
class DropDown {}
//==== Collapsibles
class Collapsible {}
//==== Accordions
class Accordion {}
//==== Carousels
class Carousel {}
//==== Progress Bar
class ProgressBar {}

//==== Animations

class AnimatedGraph {
  constructor(hover_msg = "Hover over a point to see the message", number_of_points = 7, radius = 25, velocity2 =30) {

    this.canvas = document.getElementById('animated-graph');
    let canvas_col = this.canvas.parentElement;
    this.canvas.width = this.canvas.closest('.column').clientWidth;
    this.canvas.height = this.canvas.closest('.hero__content').clientHeight;
    let self = this;
    self.hover = false;
//grabbing the root element
    canvas_col.addEventListener('mouseenter', function (event) {
      // Update mouse current status
      self.hover = true;
      document.querySelector(":root").style.setProperty("--animated-graph-msg", `"${hover_msg}"`);
    });

    canvas_col.addEventListener('mouseleave', function (event) {
      // Update mouse current status
      document.querySelector(":root").style.setProperty("--animated-graph-msg", " ");
      self.hover = false;
    });

    
    this.context = this.canvas.getContext('2d');
    // create points
    this.points = [];
     // velocity squared
    this.velocity2 = velocity2;
    this.boundaryX = this.canvas.width;
    this.boundaryY = this.canvas.height

    let colors = randomColor({
      count: number_of_points,
      luminosity: 'bright',
    });

    let icons = document.getElementsByClassName('canvas-icon');

    for (let i = 0; i < number_of_points; i++) {
      var point = {};
      point.x = Math.random()*this.boundaryX+radius;
      point.y = Math.random() *this.boundaryY+radius;
      // random vx 
      point.vx = (Math.floor(Math.random()) * 2 - 1) * Math.random();
      // vy^2 = velocity^2 - vx^2
      point.vy = Math.sqrt(this.velocity2 - Math.pow(point.vx, 2)) * (Math.random() * 2 - 1);
      point.color = colors[i];
      point.icon = icons[i];
      point.radius = radius;
      this.points.push(point);
    }

    // create connections
    for (var i = 0; i < number_of_points; i++) {
      this.points[i].buddies = [];
      for (var j = 0; j < number_of_points; j++) {
        if (i != j) {
          this.points[i].buddies.push(this.points[j]);
        }
      }
    }

    // create fixed points
    let color = randomColor({
      hue: 'blue',
    });
    this.devpoint = {};
    this.devpoint.x = radius;
    this.devpoint.y = (this.boundaryY/2)+radius;
    this.devpoint.color = color
    this.devpoint.icon = document.getElementById('speaker1');
    this.devpoint.radius = radius;
    this.userpoint = {};
    this.userpoint.x = this.boundaryX-radius;
    this.userpoint.y = (this.boundaryY/2)+radius;
    this.userpoint.color = color
    this.userpoint.icon = document.getElementById('speaker2');
    this.userpoint.radius = radius;
  
    // animate
    animate(this);
  }

  draw() {
    if (this.hover) {
      this.drawLine(this.userpoint, this.devpoint);
      this.drawCircle(this.userpoint);
      this.drawCircle(this.devpoint);
    } else {
      for (let i = 0, l = this.points.length; i < l; i++) {
        // circles
        var point = this.points[i];
        point.x += point.vx;
        point.y += point.vy;
      
        for (let i = 0; i < point.buddies.length; i++) {
          this.drawLine(point, point.buddies[i]);
        }
        this.drawCircle(point);
        // check for edge
        if (point.x < point.radius) {
          this.resetVelocity(point, 'x', 1);
        } else if (point.x > this.boundaryX - point.radius * 2) {
          this.resetVelocity(point, 'x', -1);
        } else if (point.y < 0 + point.radius) {
          this.resetVelocity(point, 'y', 1);
        } else if (point.y > this.boundaryY - point.radius * 2) {
          this.resetVelocity(point, 'y', -1);
        }
      }
    }
  }
  
  resetVelocity(point, axis, dir) {
    if(axis == 'x') {
      point.vx = dir*Math.random();  
      let vx2 = Math.pow(point.vx, 2);
      point.vy = Math.sqrt(this.velocity2 - vx2) * (Math.random()*2-1);
    } else {
      point.vy = dir*Math.random();  
      let vx2 = this.velocity2 - Math.pow(point.vy, 2);
      point.vx = Math.sqrt(vx2) * (Math.random()*2-1);
    }
  }

  drawCircle(point) {
    this.context.beginPath();
    this.context.arc(point.x, point.y, point.radius, 0, 2 * Math.PI, false);
    let gradient = this.context.createRadialGradient(point.x, point.y, 0, point.x, point.y, point.radius);
    let edge_color = tinycolor(point.color).lighten(10).toHexString();
    this.context.shadowColor = point.color;
    gradient.addColorStop(0.7, point.color);
    gradient.addColorStop(1, edge_color);
    this.context.fillStyle = gradient;
    this.context.fill();
    let offset = (point.radius * 0.7);
    this.context.drawImage(
      point.icon,
      point.x - offset, point.y - offset, offset * 2, offset * 2);
  }
  
  drawLine(p1, p2) {
    this.context.beginPath();
    this.context.moveTo(p1.x, p1.y);
    this.context.lineTo(p2.x, p2.y);
    this.context.lineWidth = 2;
    this.context.lineCap = "round";
    this.context.lineJoin = "round";
    let gradient = this.context.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
    gradient.addColorStop(0, p1.color);
    gradient.addColorStop(1, p2.color);
    this.context.strokeStyle = gradient;
    this.context.stroke();
  }    
}



