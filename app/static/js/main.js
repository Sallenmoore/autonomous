//=== define a Global object to store all of my page-level variables:
var Global = {
	currentId: undefined,
	action: 'create',
	user: {
		userName: 'Kevin',
		num_beanie_babies: '2470'
	}
};

//===My document.ready() handler...
document.addEventListener("DOMContentLoaded", () => {

	//=== do some code stuff...

	//===finally, bind my events
	bindEvents();
});

//===This function handles event binding for anything on the page
//===Bind to existing functions, not anonymous functions

function bindEvents(){
    // setup your bindings one time, when the page loads and then forget about
	//it. It will apply those bindings dynamically.

	$('#aSomeLink').on('click', function_action);

	//  ".classA" and ".classB" link an 
	//	attribute of rel="edit", I could do the following:
	$('#myTable').on('click', '.classA,.classB', function(event){
		$a = $(event.target);

		switch($a.class == 'classA'){
			case 'edit':

				// do some stuff or call a function...
				
				break;
			case 'delete':
				// do some stuff or call a function...

				break;
		}
	});

	// the above allows you to 
}

//===Then everything below this is all of the other declared functions for my page...
function function_action(){
	console.log("Did stuff")
}