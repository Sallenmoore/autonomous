$(document).ready(function(){
    $('.collapsible').collapsible();
    $('select').formSelect();

    $('.update_character').each(function(){
        console.log("trace")
        $(this).change( function(){
            $(this).submit();
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