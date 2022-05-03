$(document).ready(function(){
    $('.collapsible').collapsible();
    $('select').formSelect();
});

/***********  DICE *************/
$('#dice_selection').submit(function(event) {
    // get all the inputs into an array.
    let values =  $(this).serializeArray();
    let num_dice = $('[name="num_dice"]').val();
    let type_dice = $('[name="type_dice"]').val();
    let die = `${num_dice}d${type_dice}`;
    let bonus = $('[name="bonus"]').val();
    if(bonus){
        die = `${die}+${bonus}`;
    };
    console.log(die);
    var timeoutId, lastFace, transitionDuration = 500, animationDuration  = 3000;
    $.ajax(`http://api/dice/roll/${die}`)
        .done(function(die_data) {
            alert(die_data['result']);
            // let sides = 20;
            // let initialSide = 1;
            // $die_tray = $('#dice_tray')
            // $die.addClass('rolling');
            // reset();
            // rollTo(die_data['result']);
            // timeoutId = setTimeout(function () {
            //     $die.removeClass('rolling');
            //     rollTo(randomFace());
            // }, animationDuration);
        }).fail(function() {
            alert( "error" );
        });

    // function randomFace(sides){
    //     var face = Math.floor((Math.random() * sides)) + initialSide;
    //     lastFace = face == lastFace ? randomFace(sides) : face;
    //     return face;
    // }

    // function rollTo(face) {
    //     clearTimeout(timeoutId);
    //     $('[href=' + face + ']').addClass('active');
    //     $die.attr('data-face', face);
    // }

    // function reset() {
    //     $die.attr('data-face', null).removeClass('rolling');
    // }
    event.preventDefault();
});

$('#reference_search').keyup(function(event) {
    let search_term = $('#search_term').val();
    console.log(search_term);
    if(search_term.length >= 3) {
        let values =  $(this).serializeArray();
        console.log(values);
        fetch(`api:8000/compendium/search?search_term=${search_term}`)
            .then(response => {
                console.log(response.json());
            }).catch(error => {
                console.log(error);
            });
        }
    }
);