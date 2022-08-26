$(document).ready(function(){
    //$('.collapsible').collapsible();
    //$('select').formSelect();
    M.AutoInit();

    $('.update_character').each(function(){
        $(this).change( function(){
            $(this).submit();
        });
    });

    var sortable = Sortable.create($('#character_initiative')[0]);

});

$('#next_initiative').click(function(){
    var prev = $("#character_initiative li:first-child");
    $.unique(prev).each(function(i) {
      $(this).slideUp(function() {
        $(this).appendTo(this.parentNode).slideDown();
      });
    });
});

$('#search_term').keyup(function(event) {
    let search_term = $(this).val();
    if(search_term.length >= 3) {
        let endpoint = $("#endpoint").val();
        //search_term = $.param(search_term);
        //console.log(search_term);
        fetch(`/compendium?endpoint=${endpoint}&search_term=${search_term}`)
            .then(response => response.json())
            .then((obj) => {
                $('#auto_search_results').empty()
                obj.results.forEach(function(item){
                    let icon = "broken_image"
                    if (item.route.includes("spell")){
                        icon = "contactless"
                    }else if (item.route.includes("monster")){
                        icon = "android"
                    }else if (item.route.includes("magic")){
                        icon = "auto_fix_normal"
                    }
                    let detail = ""
                    for (let key in item) {
                        if(!("text", "highlighted", "document_slug", "route", "slug").includes(key)){
                            detail += `<li>${key}: ${item[key]}<div class="divider"></div></li>`
                        }
                    }
                    let result = `
                    <li>
                        <div class="collapsible-header"> 
                           <i class="material-icons">${icon}</i>
                            ${item.name}
                        </div>
                        <div class="collapsible-body">
                            <ul>
                                ${detail}
                            </ul>
                        </div>
                    </li>
                    `;
                    $('#auto_search_results').append(result)
                });
                $('#search_results').show();
            }).catch(error => {
                console.log(error);
            });
    }else{
        $('#search_results').hide();
    }
});

$('.add_to_initiative').click(function(event) {
    console.log($(this)[0].checked)
    
    let char_name = $(this).parent().siblings('input[name="char_name"]').val()
    console.log(char_name)
    if($(this)[0].checked){
        $('#character_initiative').append(`<li class="collection-item">${char_name}</li>`);
    }else{
        $('#character_initiative').children('li').each(function(){
            if($(this).text() == char_name){
                $(this).remove();
            }
        });
    }
});