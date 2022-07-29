$(document).ready(function(){
    $('.collapsible').collapsible();
    $('select').formSelect();

    $('.update_character').each(function(){
        console.log("trace")
        $(this).change( function(){
            $(this).submit();
        });
    });

    var initiative_list = document.getElementById('character_initiative');
    var sortable = Sortable.create(initiative_list);
});

$('#next_initiative').click(function(){
    var prev = $("#character_initiative li:first-child");
    $.unique(prev).each(function(i) {
      $(this).slideUp(function() {
        $(this).appendTo(this.parentNode).slideDown();
      });
    });
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