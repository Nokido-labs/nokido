document.getElementById('loginForm').addEventListener('submit', async function(event) {
    event.preventDefault();

    const user = document.getElementById('username').value;
    const passwd = document.getElementById('password').value;

    // create a database query
    const query = {
        "name": user,
        "password": passwd
    };

    // JSON format
    const data = JSON.stringify(query);

    const response = await fetch('/demo_access/ab19cf886b5a8facb01403b6abbfa440.html', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: data
    });

    if (response.ok) {
        const msg = await response.json();
        document.getElementById('results').innerText = msg.message;

        // check for redirection 
        var complete_message = msg.message;
        if (complete_message == "You are logged in ! Redirect in progress...") {
            setTimeout(() => {
                document.location = "/demo_access/ab19cf886b5a8facb01403b6abbfa440/panel"
            }, "2000");
        }
    } else {
        console.error('Failed to fetch data');
    }
});