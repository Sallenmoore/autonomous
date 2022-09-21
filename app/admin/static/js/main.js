$(document).ready(function(){
    //$('.collapsible').collapsible();
    //$('select').formSelect();
    M.AutoInit();
    $('.update_character').each(function(){
        $(this).change( function(){
            $(this).submit();
        });
    });

    var sortable = Sortable.create($('#battle_initiative')[0]);

});

$('#next_initiative').click(function(){
    var prev = $("#character_initiative li:first-child");
    $.unique(prev).each(function(i) {
      $(this).slideUp(function() {
        $(this).appendTo(this.parentNode).slideDown();
      });
    });
});

update_search_results = function(event) {
    let search_term = $('#search').val();
    let key = $('#search').attr('name');
    let endpoint = $("#endpoint").val();
    if(search_term.length >= 3) {
        console.log(search_term);
        const dataToSend = JSON.stringify({[key]: search_term, "endpoint":endpoint});
        fetch(`/compendium`, {
            credentials: "same-origin",
            mode: "same-origin",
            method: "post",
            headers: { "Content-Type": "application/json" },
            body: dataToSend
        }).then(response => {
            console.log("Status: " + response.status)
            if (response.status === 200) {
                return response.json()
            } else {
                return Promise.reject("server")
            }
        }).then((obj) => {
                $('#auto_search_results').empty()
                //console.log(obj)
                /////////// SPELLS ///////////
                let spell_table = `
                    <h3>Spells</h3>
                    <table class="highlight">
                        <thead>
                            <th>Name</th>
                            <th>More Info</th>
                        </thead>
                `
                /////////// Monsters ///////////
                let monster_table = `
                    <h3>Monsters</h3>
                    <table class="highlight">
                        <thead>
                            <th>Name</th>
                            <th>More Info</th>
                            <th>Initiative</th>
                        </thead>
                `
                /////////// Item ///////////
                let item_table = `
                    <h3>Items</h3>
                    <table class="highlight">
                        <thead>
                            <th>Name</th>
                            <th>More Info</th>
                        </thead>
                `
                ////////////// BUILD TABLES //////////////
                spells = false
                monsters = false
                items = false
                obj.forEach(function(item){
                    let modal = `
                    <div id="modal-${item.model_class}-${item.pk}" class="modal">
                        <div class="modal-content">
                            <h4>${item.name}</h4>
                    `;
                    for (let key in item) {
                        modal += `
                        <div class="input-field col s12">
                            <input value="${item[key]}" name="${key}" type="text">
                            <label for="${key}">${key}</label>
                        </div>
                        `;
                    }
                    modal += `
                        </div>
                        <div class="modal-footer">
                            <a href="#!" class="modal-close waves-effect waves-green btn-flat">Close</a>
                        </div>
                    </div>
                    `;

                    let row = `
                        <tr>
                            <td>
                                ${item.name}
                            </td>
                        <td>
                            <a class="waves-effect waves-light btn-small modal-trigger" href="#modal-${item.model_class}-${item.pk}">
                                more info
                            </a>
                            ${modal}
                        </td>
                    `;
                    if (item.model_class == "Monster"){
                        row += `
                            <td>
                                <a id="initative_${item.model_class}_${item.pk}" name="${item.name}" class="btn-floating btn-small waves-effect waves-light red add_to_mob_initiative"><i class="material-icons">add</i></a>
                            </td>
                        `;
                    }
                    row +=`</tr>
                    `;
                    if (item.model_class == "Spell"){
                        spell_table += row;
                        spells = true;
                    }else if (item.model_class == "Monster"){
                        monster_table += row;
                        monsters = true;
                    }else if (item.model_class == "Item"){
                        item_table += row;
                        items = true;
                    }

                });
                if (spells) $('#auto_search_results').append(monster_table);
                if (monsters) $('#auto_search_results').append(spell_table);
                if (items) $('#auto_search_results').append(item_table);
                $('#auto_search_results').show();
            }).catch(error => {
                console.log(error);
            });
    }else{
        $('#auto_search_results').hide();
    }
};

// ################## Initiative Functions ##################
// Add to random spot on the list
function add_to_initiative(event) {
    let name = $(this).attr('name');
    let inits = $('#battle_initiative > .collection-item')
    let index = Math.floor(Math.random()*inits.length);
    $(inits[index]).after(`
            <li class="collection-item">
                <div class="row">
                    <div class="col s10 truncate initiative_name">
                        <i class="material-icons">monster</i> ${name}
                    </div>
                    <div class="col s2">
                        <a class="waves-effect waves-light btn-small btn-floating red remove_from_initiative">
                            <i class="material-icons">remove</i>
                        </a>
                    </div>
                <div>
            </li>
    `);
}

$('#battle_initiative').on('click', ".remove_from_initiative", function(event) {
    let to_remove = $(this).closest(".collection-item");
    to_remove.remove();
});


// ########## Compendium Functions ##########
$('#update_compendium').click(function(){    
    fetch(`//api:44666/compendium/update_compendium`, {
        method: "get"
    }).then(response => {
        console.log("Status: " + response.status)
        if (response.status === 200) {
            return response.json()
        } else {
            return Promise.reject("server")
        }
    });
});

/////////////// Bindings ///////////
// Search
$('#search').keyup(update_search_results);
$('#endpoint').change(update_search_results);
// Initiative
$('.add_to_initiative').on('click', add_to_initiative);
$('#auto_search_results').on('click', ".add_to_mob_initiative", add_to_initiative);




