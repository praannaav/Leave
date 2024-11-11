$(document).ready(function() {
    // Load replacements
    $.getJSON('/get_replacements', function(data) {
        var replacementList = $('#replacement-list');
        if (data.length === 0) {
            replacementList.append('<li class="list-group-item">No replacements assigned.</li>');
        } else {
            data.forEach(function(item) {
                replacementList.append('<li class="list-group-item">' +
                    item.employee_on_leave + ' is replaced by ' + item.replacement_employee +
                    ' on ' + item.date +
                    '</li>');
            });
        }
    });
});
