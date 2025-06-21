/**
 * Validação de datas para filtros de listagem
 * Garante que a data final nunca seja menor que a data inicial nos formulários de filtro
 * Validação ocorre apenas no momento do envio do formulário
 */
document.addEventListener('DOMContentLoaded', function() {
    // Encontrar todos os formulários de filtro (presente em todas as páginas de listagem)
    const filterForms = document.querySelectorAll('form.filter-form');
    
    filterForms.forEach(filterForm => {
        const startDateInput = filterForm.querySelector('#start_date');
        const endDateInput = filterForm.querySelector('#end_date');
        
        if (startDateInput && endDateInput) {
            // Função para validar as datas apenas no momento do envio do formulário
            filterForm.addEventListener('submit', function(event) {
                if (startDateInput.value && endDateInput.value) {
                    const startDate = new Date(startDateInput.value);
                    const endDate = new Date(endDateInput.value);
                    
                    if (endDate < startDate) {
                        event.preventDefault();
                        alert('A data final não pode ser menor que a data inicial.');
                        endDateInput.value = startDateInput.value;
                    }
                }
            });
        }
    });
});
